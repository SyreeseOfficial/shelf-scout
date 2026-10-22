"""`python -m shelf_scout doctor`: a pass/fail checklist of everything that has to work for a real alert to reach you.

Unlike `poll-once` this does send real messages (a quiet "doctor ping" to each enabled channel), because the
only way to know a channel works is to use it.
"""
import asyncio
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from . import db, pollers
from .models import Alert, Layer, Reading, StockState
from .notifiers import build_notifiers
from .pollers import PollError
from .trackers.feeds import build_feed_pollers

SERVICE = "shelf-scout"


@dataclass
class Check:
    ok: bool
    name: str
    detail: str   # on failure: what failed, and the fix


def _fix_for(detail: str) -> str:
    if detail.startswith("blocked"):
        return "the site's bot check is refusing us. shelf-scout won't get around it: it keeps backing off, and the tracker feeds plus the retailer's notify-me alerts cover it."
    if "settings.json" in detail:
        return "set it in Settings (http://127.0.0.1:8765/settings), or turn the retailer off there."
    return "check the link/id in Settings, and see README 'Troubleshooting' item 3."


async def check_channels(settings: dict, notifiers=None) -> list[Check]:
    out = []
    ping = Alert(event_id=0, loud=False, notice="shelf-scout doctor: test ping", msrp_cents=settings["msrp_cents"],
                 rows=[Reading("bot", StockState.ERROR, Layer.PAGE, "", None, None, None, "If you can read this, this channel works.", time.time())])
    for n in notifiers if notifiers is not None else build_notifiers(settings):
        try:
            await n.send(ping)
            out.append(Check(True, f"channel {n.name} sends", "ping sent: confirm it arrived"))
        except Exception as e:
            out.append(Check(False, f"channel {n.name} sends", f"{type(e).__name__}: {e}. Fix: check this channel's settings in Settings (and your internet)."))
    if not out:
        out.append(Check(False, "at least one channel enabled", "no channel is enabled, so nothing can reach you. Fix: turn one on in Settings."))
    return out


async def check_ack_topic(settings: dict, client: httpx.AsyncClient) -> Check:
    cfg = settings["channels"]["ntfy"]
    name = "phone ack topic reachable"
    if not cfg["enabled"]:
        return Check(True, name, "ntfy is off, so phone ack isn't used")
    if not cfg["ack_topic"]:
        return Check(False, name, "channels.ntfy.ack_topic is empty, so the phone's Acknowledge button can't work. Fix: set it in Settings.")
    try:
        r = await client.get(f"{cfg['server'].rstrip('/')}/{cfg['ack_topic']}/json", params={"poll": "1", "since": "1s"})
        r.raise_for_status()
        return Check(True, name, f"{cfg['server']} answered")
    except httpx.HTTPError as e:
        return Check(False, name, f"{type(e).__name__}: {e}. Fix: check channels.ntfy.server and your internet.")


async def check_sources(settings: dict, client: httpx.AsyncClient) -> list[Check]:
    out = []
    for name, cfg in settings["retailers"].items():
        if not cfg["enabled"]:
            continue
        poller = pollers.build(name, client, lambda: settings)
        if poller is None:
            continue
        try:
            readings = await poller.check()
        except PollError as e:
            readings = [poller.error("", e)]
        good = [r for r in readings if r.state is not StockState.ERROR]
        if good:
            out.append(Check(True, f"retailer {name} readable", ", ".join(sorted({r.state.value for r in good}))))
        else:
            detail = readings[0].detail or "no reading"
            out.append(Check(False, f"retailer {name} readable", f"{detail}. Fix: {_fix_for(detail)}"))
    scratch = db.connect(Path(":memory:"))   # news feeds save to the database; doctor must not touch the real one
    for fp in build_feed_pollers(client, lambda: settings, scratch, None):
        if not fp.enabled:
            continue
        try:
            await fp.check()
            out.append(Check(True, f"feed {fp.retailer} readable", "ok"))
        except PollError as e:
            out.append(Check(False, f"feed {fp.retailer} readable", f"{e}. Fix: check its URL in Settings; Reddit also rate-limits at busy times."))
    return out


async def check_service() -> Check:
    name = "systemd service active"
    try:
        proc = await asyncio.create_subprocess_exec("systemctl", "--user", "is-active", SERVICE,
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        state = (await proc.communicate())[0].decode().strip()
    except FileNotFoundError:
        return Check(False, name, "systemctl not found. Fix: this check needs systemd; run shelf-scout another way.")
    if state == "active":
        return Check(True, name, "running")
    return Check(False, name, f"service is {state or 'not installed'}. Fix: follow README 'Run it as a service'.")


async def run_doctor(settings: dict, db_path: Path, notifiers=None, check_systemd: bool = True) -> list[Check]:
    results = [Check(True, "settings valid", "settings.json loaded")]   # an invalid file never gets this far
    try:
        db.connect(db_path).execute("CREATE TABLE IF NOT EXISTS _doctor (x)")
        results.append(Check(True, "database writable", str(db_path)))
    except Exception as e:
        results.append(Check(False, "database writable", f"{e}. Fix: check the folder is writable: {db_path.parent}"))
    async with httpx.AsyncClient(headers={"User-Agent": pollers.USER_AGENT}, timeout=15, follow_redirects=True) as client:
        results += await check_channels(settings, notifiers)
        results.append(await check_ack_topic(settings, client))
        results += await check_sources(settings, client)
    if check_systemd:
        results.append(await check_service())
    return results


def report(results: list[Check]) -> int:
    for c in results:
        print(f"[{'PASS' if c.ok else 'FAIL'}] {c.name}: {c.detail}")
    bad = sum(not c.ok for c in results)
    print(f"\n{len(results) - bad} passed, {bad} failed." + ("" if not bad else " Each FAIL line ends with what to do."))
    return 1 if bad else 0
