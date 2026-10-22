"""Dashboard and settings UI: FastAPI + Jinja, server-rendered, a little vanilla JS. Local only, no login (v1).

Everything here runs on the service's own event loop (handlers are `async def`), which is what lets it share
the engine and the SQLite connection safely. Saving settings validates, writes settings.json atomically, and
swaps `engine.settings`; pollers, feeds and notifiers read it fresh each time, so no restart is needed.
"""
import asyncio
import copy
import logging
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .. import config
from ..notifiers import price_label
from ..pollers import ParseError, to_cents
from ..trackers import events

log = logging.getLogger("shelf_scout.web")
HERE = Path(__file__).parent
SECRET_KEYS = {"api_key", "webhook_url", "bot_token", "smtp_password", "alert_topic", "ack_topic"}
MONEY_KEYS = {"msrp_cents": "MSRP", "tolerance_cents": "Tolerance"}
LOCAL_STOCK = {"target"}   # the only retailer where we can see per-store stock (see README table)
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def ago(t: float | None) -> str:
    if not t:
        return "never"
    s = max(0, int(time.time() - t))
    return f"{s}s ago" if s < 90 else f"{s // 60} min ago" if s < 5400 else f"{s // 3600} h ago" if s < 172800 else f"{s // 86400} d ago"


def clock(t: float | None) -> str:
    return datetime.fromtimestamp(t).strftime("%b %d %H:%M") if t else ""


def mask(value: str) -> str:
    return "" if not value else "set (…" + value[-4:] + ")" if len(value) > 8 else "set"


def duration(start: float, end: float | None) -> str:
    if end is None:
        return "still in stock"
    m = int((end - start) / 60)
    return f"{int(end - start)}s" if m < 1 else f"{m} min" if m < 120 else f"{m // 60} h {m % 60} min"


def form_value(form: dict, name: str, current):
    """Turn one submitted field back into the type of the setting it edits. Text that isn't a number is kept
    as-is, so config.validate rejects it with a message naming the setting."""
    if isinstance(current, bool):
        return name in form                               # unchecked boxes aren't sent at all
    if isinstance(current, list):
        return [l.strip() for l in form.get(name, "").splitlines() if l.strip()]   # urls / skus: one per line
    raw = form.get(name, "").strip()
    if isinstance(current, int):
        return int(raw) if raw.lstrip("-").isdigit() else raw
    return raw


def read_section(form: dict, prefix: str, current: dict) -> dict:
    out = {}
    for k, v in current.items():
        val = form_value(form, prefix + k, v)
        out[k] = v if (k in SECRET_KEYS and val == "") else val   # blank secret = unchanged
    return out


def cents_from_form(form: dict, key: str, current: int) -> int:
    raw = form.get(key, "").strip()
    try:
        return to_cents(raw)
    except ParseError:
        raise config.ConfigError(f'settings: {MONEY_KEYS[key]} must be a dollar amount like 899.99 (got {raw!r})') from None


def build_settings(form: dict, cur: dict) -> dict:
    """Candidate settings from the submitted form (not validated yet)."""
    new = copy.deepcopy(cur)
    for k, v in cur.items():
        if k in MONEY_KEYS:
            new[k] = cents_from_form(form, k, v)
        elif not isinstance(v, (dict, list)):
            new[k] = form_value(form, k, v)
    for name, r in cur["retailers"].items():
        new["retailers"][name] = read_section(form, f"r_{name}_", r)
    for name, c in cur["channels"].items():
        new["channels"][name] = read_section(form, f"c_{name}_", c)
    new["dashboard"] = read_section(form, "d_", cur["dashboard"])
    # Quiet hours: one row per existing entry plus a blank one; a row with no days ticked and no times is ignored.
    quiet = []
    for i in range(len(cur["quiet_hours"]) + 1):
        if f"q{i}_remove" in form:
            continue
        days = [d for d in range(7) if f"q{i}_day{d}" in form]
        start, end = form.get(f"q{i}_start", "").strip(), form.get(f"q{i}_end", "").strip()
        if days or start or end:
            quiet.append({"days": days, "start": start, "end": end, "mode": form.get(f"q{i}_mode", "mute")})
    new["quiet_hours"] = quiet
    feeds = []
    for i in range(len(cur["feeds"]) + 1):
        if f"f{i}_remove" in form or not form.get(f"f{i}_name", "").strip():
            continue
        base = cur["feeds"][i] if i < len(cur["feeds"]) else {"enabled": True, "interval_seconds": 60}
        feeds.append({"name": form[f"f{i}_name"].strip(), "url": form.get(f"f{i}_url", "").strip(), "type": "rss",
                      "role": form.get(f"f{i}_role", "alert"), "enabled": f"f{i}_enabled" in form,
                      "interval_seconds": form_value(form, f"f{i}_interval", base["interval_seconds"])})
    new["feeds"] = feeds
    return new


def create_app(engine, conn, settings_path: Path) -> FastAPI:
    app = FastAPI(title="shelf-scout", docs_url=None, redoc_url=None, openapi_url=None)
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.globals.update(ago=ago, clock=clock, mask=mask, duration=duration, price_label=price_label,
                                 SECRET_KEYS=SECRET_KEYS, MONEY_KEYS=MONEY_KEYS, DAYS=DAYS, LOCAL_STOCK=LOCAL_STOCK)
    tests: set[asyncio.Task] = set()   # keeps background test tasks alive until they finish

    @app.middleware("http")
    async def same_site_only(request: Request, call_next):
        # No login in v1, so refuse form posts that another website's page triggered in the owner's browser.
        origin = request.headers.get("origin")
        if request.method == "POST" and origin and urlparse(origin).netloc != request.headers.get("host"):
            return PlainTextResponse("Blocked: this request came from another website.", status_code=403)
        return await call_next(request)

    def status() -> dict:
        s = engine.settings
        return {
            "msrp": s["msrp_cents"], "paused": engine.paused, "waiting": engine.waiting,
            "readings": conn.execute("SELECT * FROM readings ORDER BY retailer, state != 'in_stock', price_cents IS NULL, price_cents").fetchall(),
            "health": conn.execute("SELECT * FROM health ORDER BY retailer").fetchall(),
            "history": conn.execute("SELECT * FROM events ORDER BY started DESC LIMIT 25").fetchall(),
            "upcoming": events.upcoming(conn),
        }

    @app.get("/")
    async def dashboard(request: Request):
        return templates.TemplateResponse(request, "dashboard.html", status())

    @app.get("/partial/status")
    async def partial(request: Request):
        return templates.TemplateResponse(request, "_status.html", status())

    @app.post("/api/{action}")
    async def action(action: str):
        if action == "ack":
            await engine.ack()
        elif action in ("test", "test-quiet"):
            t = asyncio.create_task(engine.fire_test(quiet=action == "test-quiet"))
            tests.add(t)
            t.add_done_callback(tests.discard)
        elif action == "pause":
            engine.pause()
        elif action == "resume":
            engine.resume()
        else:
            return JSONResponse({"ok": False, "error": f"unknown action {action!r}"}, status_code=404)
        return {"ok": True}

    def settings_page(request, s, error=None, saved=False):
        return templates.TemplateResponse(request, "settings.html", {"s": s, "error": error, "saved": saved, "retailer_names": list(s["retailers"])})

    @app.get("/settings")
    async def settings_form(request: Request):
        return settings_page(request, engine.settings, saved="saved" in request.query_params)

    @app.post("/settings")
    async def settings_save(request: Request):
        form = {k: v[0] for k, v in parse_qs((await request.body()).decode(), keep_blank_values=True).items()}
        # Checkbox groups repeat a name, but ours are one-name-per-box, so the first value is enough.
        candidate = None
        try:
            candidate = build_settings(form, engine.settings)
            new = config.validate(candidate)
            config.save(settings_path, new)
        except config.ConfigError as e:
            return settings_page(request, candidate or engine.settings, error=str(e))
        engine.settings = new   # applies live: pollers, feeds and notifiers read engine.settings each time
        log.info("settings saved from the dashboard and applied")
        return RedirectResponse("/settings?saved=1", status_code=303)

    return app
