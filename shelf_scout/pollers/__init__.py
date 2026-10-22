"""Poller framework: base class, block detection, and the per-retailer loop with back-off and health.

A poller that can't read a page raises PollError (or returns an ERROR reading). It must NEVER
return OUT_OF_STOCK for a page it didn't understand: the engine ignores ERROR, so a block can
never look like "sold out" and can never close a real in-stock event.
"""
import asyncio
import importlib
import logging
import random
import re
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import httpx

from ..models import Layer, Reading, StockState

log = logging.getLogger("shelf_scout.poll")

# Honest and identifiable on purpose: no browser impersonation. If a retailer won't talk to this, we back off.
USER_AGENT = "shelf-scout/0.1 (personal PS5 Pro stock alert; about one request a minute)"
MAX_BACKOFF = 30 * 60
BLOCK_STATUSES = {403, 429, 503}
# Challenge pages often come back as HTTP 200 (Amazon does), so status codes alone would miss them.
BLOCK_BODY_MARKERS = ("validatecaptcha", "enter the characters you see below", "px-captcha", "_incapsula_resource", "cf-chl")
BLOCK_TITLE_MARKERS = ("robot check", "access denied", "are you a human", "just a moment", "pardon our interruption", "captcha")


class PollError(Exception):
    """Couldn't read the listing. The message says what failed and what to try."""


class Blocked(PollError):
    """The retailer is refusing us (rate limit, CAPTCHA, challenge page)."""


class ParseError(PollError):
    """We got a page but it isn't the shape we expect (retailer changed it, or wrong URL)."""


def to_cents(value) -> int:
    """'1,049.99' / 899.0 -> cents. Decimal avoids float errors like 899.99 * 100 = 89998.999..."""
    try:
        return int(Decimal(str(value).replace(",", "").replace("$", "").strip()) * 100)
    except InvalidOperation:
        raise ParseError(f"can't read a price from {value!r}") from None


def raise_if_blocked(r: httpx.Response) -> None:
    where = r.url.host
    if r.status_code in BLOCK_STATUSES:
        raise Blocked(f"HTTP {r.status_code} from {where} (rate limit or bot check)")
    if "html" in r.headers.get("content-type", ""):
        text = r.text.lower()
        m = re.search(r"<title[^>]*>(.*?)</title>", text, re.S)
        page_title = m.group(1).strip() if m else ""
        hit = next((k for k in BLOCK_BODY_MARKERS if k in text), None) or next((k for k in BLOCK_TITLE_MARKERS if k in page_title), None)
        if hit:
            raise Blocked(f"{where} served a bot-check page (matched {hit!r})")
    if any(k in str(r.url).lower() for k in ("captcha", "challenge", "/blocked")):  # walmart.com/blocked?url=...
        raise Blocked(f"redirected to a challenge page: {r.url}")


class Poller:
    """Subclasses set `retailer` and `layer`, and implement check()."""
    retailer: str
    layer: Layer
    empty_ok = False  # True for sources where "no readings this time" is normal (tracker feeds)

    def __init__(self, client: httpx.AsyncClient, get_settings):
        self.client = client
        self.get_settings = get_settings  # a function, so edits to settings apply on the next poll

    @property
    def cfg(self) -> dict:
        return self.get_settings()["retailers"][self.retailer]

    @property
    def enabled(self) -> bool:
        return self.cfg.get("enabled", True)

    async def check(self) -> list[Reading]:
        raise NotImplementedError

    async def get(self, url: str, **kw) -> httpx.Response:
        """GET that turns blocks, dead links and network failures into PollError."""
        try:
            r = await self.client.get(url, **kw)
        except httpx.TransportError as e:
            raise PollError(f"network error reaching {url}: {type(e).__name__}: {e}. "
                            "Check your internet; the retailer may also be dropping our connection.") from e
        raise_if_blocked(r)
        if r.status_code >= 400:
            raise PollError(f"HTTP {r.status_code} from {url}. If this is a product link, it may be dead: update it in settings.json")
        return r

    def error(self, url: str, e: Exception) -> Reading:
        detail = f"blocked: {e}" if isinstance(e, Blocked) else str(e) or type(e).__name__
        return Reading(self.retailer, StockState.ERROR, self.layer, url, None, None, None, detail, time.time())

    async def each(self, items: list[tuple[str, str]], fn, missing: str) -> list[Reading]:
        """Run fn(url, key) per listing. One bad listing becomes an ERROR reading; the others still count."""
        if not items:
            raise PollError(missing)
        out: list[Reading] = []
        for url, key in items:
            try:
                out += await fn(url, key)
            except PollError as e:
                out.append(self.error(url, e))
        return out


def build(name: str, client: httpx.AsyncClient, get_settings) -> Poller | None:
    """Poller for a retailer name, or None if its module doesn't exist yet."""
    module = f"{__name__}.{name}"
    try:
        return importlib.import_module(module).POLLER(client, get_settings)
    except ModuleNotFoundError as e:
        if e.name != module:
            raise  # a real missing dependency inside the module, not "retailer not built yet"
        return None


@dataclass
class RunState:
    fails: int = 0       # consecutive failed polls; resets on success
    blocked: bool = False  # True from the first block until the next success (one notification per stretch)


def _record(conn, name: str, readings: list[Reading], st: RunState, ok: bool, blocked: bool) -> None:
    """Latest snapshot per retailer into `readings`, and the heartbeat into `health`."""
    errors = [r.detail for r in readings if r.state is StockState.ERROR]
    now = time.time()
    with conn:
        conn.execute("DELETE FROM readings WHERE retailer=?", (name,))
        conn.executemany(
            "INSERT OR REPLACE INTO readings (retailer,url,layer,detail,state,price_cents,seller,fulfillment,at) VALUES (?,?,?,?,?,?,?,?,?)",
            [(r.retailer, r.url, r.layer.value, r.detail or "", r.state.value, r.price_cents, r.seller,
              r.fulfillment.value if r.fulfillment else None, r.at) for r in readings])
        conn.execute(
            "INSERT INTO health (retailer,last_ok,error_count,state,note) VALUES (?,?,?,?,?) "
            "ON CONFLICT(retailer) DO UPDATE SET last_ok=COALESCE(excluded.last_ok,last_ok), "
            "error_count=excluded.error_count, state=excluded.state, note=excluded.note",
            (name, now if ok else None, st.fails, "ok" if ok else "blocked" if blocked else "error", "; ".join(errors) or None))


async def poll_step(poller: Poller, engine, conn, st: RunState) -> float:
    """One poll: record it, feed the engine, return how many seconds to wait before the next."""
    name, interval = poller.retailer, poller.cfg["interval_seconds"]
    try:
        readings = await poller.check()
    except Exception as e:  # a crashing poller must never take the loop (or other retailers) down
        if not isinstance(e, PollError):
            log.exception("%s poller crashed; will retry", name)
        readings = [poller.error("", e)]
    if not readings and not poller.empty_ok:
        readings = [poller.error("", PollError("poller returned no readings (bug in the poller)"))]
    ok = not readings or any(r.state is not StockState.ERROR for r in readings)
    blocked = any((r.detail or "").startswith("blocked") for r in readings if r.state is StockState.ERROR)
    st.fails = 0 if ok else st.fails + 1
    _record(conn, name, readings, st, ok, blocked)

    if ok:
        if st.blocked:
            log.info("%s: recovered, back to normal polling", name)
        st.blocked = False
        log.info("%s: poll ok, %s", name, ", ".join(f"{r.state.value}" for r in readings) or "nothing new")
        wait = interval
    else:
        wait = min(interval * 2 ** st.fails, MAX_BACKOFF)  # doubles each failure, resets on success
        log.warning("%s: poll failed (%s). Retrying in %.0fs", name, readings[0].detail, wait)
        if blocked and not st.blocked:
            st.blocked = True
            await engine.notice(
                f"{name} is blocking shelf-scout",
                f"{readings[0].detail}\nBacking off (next try in about {wait / 60:.0f} min, doubling up to 30 min). "
                f"You won't get {name} alerts until it recovers, so lean on your retailer notify-me alerts meanwhile.",
                readings[0].url)
    for r in readings:
        await engine.handle_reading(r)
    return wait * random.uniform(0.8, 1.2)  # jitter so we don't poll on a metronome


async def run_poller(poller: Poller, engine, conn) -> None:
    """Poll forever. A crash anywhere in one iteration (even outside check(), e.g. a database error) is logged and
    retried after a growing pause; it can only ever stop this one poller, never the others or the service."""
    st, crashes = RunState(), 0
    while True:
        try:
            if engine.paused or not poller.enabled:  # re-checked every loop, so the dashboard's switches apply live
                await asyncio.sleep(2)
                continue
            wait = await poll_step(poller, engine, conn, st)
            crashes = 0
        except Exception:  # (CancelledError is not an Exception, so stopping the service still works)
            crashes += 1
            wait = min(5 * 2 ** crashes, 300)
            log.exception("%s: poller loop crashed (crash #%d in a row); restarting it in %ss. Other sources are unaffected",
                          poller.retailer, crashes, wait)
        await asyncio.sleep(wait)
