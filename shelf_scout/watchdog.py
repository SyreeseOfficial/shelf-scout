"""Self-monitoring: tells the owner when shelf-scout can't see anything, and checks the setup at startup.

A bot that has gone blind looks exactly like a bot with nothing to report, so silence is never good news here.
"""
import asyncio
import logging
import time

log = logging.getLogger("shelf_scout.watchdog")
TICK_SECONDS = 30


class Watchdog:
    """Every tick, find sources with no good poll for `no_poll_alert_minutes`. One message when sources go stale,
    one when they recover. Messages are grouped per tick, so a dead network is one message, not one per retailer."""

    def __init__(self, engine, started: float | None = None):
        self.engine = engine
        self.started = started or time.time()   # a source that has never worked counts from startup
        self.stale: set[str] = set()

    def find_stale(self, now: float) -> tuple[set[str], set[str]]:
        """(stale sources, all active sources). Only enabled sources that have polled at least once count."""
        s = self.engine.settings
        interval = {n: c["interval_seconds"] for n, c in s["retailers"].items() if c["enabled"]}
        interval.update({f["name"]: f["interval_seconds"] for f in s["feeds"] if f["enabled"]})
        stale, active = set(), set()
        for row in self.engine.conn.execute("SELECT retailer, last_ok FROM health"):
            name = row["retailer"]
            if name not in interval:
                continue
            active.add(name)
            # Never count time spent paused, and allow 3 polls of slack for slow feeds (a 15 min news feed isn't "stale" at 10).
            last = max(row["last_ok"] or self.started, self.engine.resumed_at)
            if now - last > max(s["no_poll_alert_minutes"] * 60, 3 * interval[name]):
                stale.add(name)
        return stale, active

    async def tick(self, now: float | None = None) -> None:
        if self.engine.paused:
            return
        minutes = self.engine.settings["no_poll_alert_minutes"]
        stale, active = self.find_stale(now or time.time())
        new, back = stale - self.stale, (self.stale - stale) & active
        self.stale = stale
        if new and stale == active:
            await self.engine.notice(
                "shelf-scout is BLIND: no source is working",
                f"None of {', '.join(sorted(active))} has had a good poll in {minutes}+ minutes, so you will NOT get restock alerts. "
                "Check your internet connection and the dashboard's Bot health panel. Rely on your retailer notify-me alerts until this clears.")
        elif new:
            await self.engine.notice(
                f"shelf-scout can't poll: {', '.join(sorted(new))}",
                f"No good poll from {', '.join(sorted(new))} in {minutes}+ minutes, so you won't get alerts from {'it' if len(new) == 1 else 'them'}. "
                "See the dashboard's Bot health panel for the reason.")
        if back:
            still = f" Still down: {', '.join(sorted(stale))}." if stale else ""
            await self.engine.notice(f"shelf-scout recovered: {', '.join(sorted(back))}", f"Polling works again.{still}")

    async def run(self) -> None:
        while True:
            await asyncio.sleep(TICK_SECONDS)
            try:
                await self.tick()
            except Exception:
                log.exception("watchdog check failed; will try again")


def startup_check(settings: dict) -> list[tuple[str, str]]:
    """(level, message) lines describing what is and isn't set up. Warnings say what will NOT work."""
    out = []
    ch = settings["channels"]
    on = [n for n, c in ch.items() if c["enabled"]]
    out.append(("info", f"channels enabled: {', '.join(on) or 'none'}"))
    if not on:
        out.append(("warning", "NO notification channel is enabled: restocks will only show on the dashboard. Turn one on in Settings."))
    if ch["ntfy"]["enabled"]:
        if not ch["ntfy"]["alert_topic"]:
            out.append(("warning", "ntfy is on but channels.ntfy.alert_topic is empty: phone alerts WON'T be sent. Set it in Settings."))
        if not ch["ntfy"]["ack_topic"]:
            out.append(("warning", "channels.ntfy.ack_topic is empty: the phone's Acknowledge button WON'T stop repeats. Set it in Settings."))
    if ch["discord"]["enabled"] and not ch["discord"]["webhook_url"]:
        out.append(("warning", "Discord is on but its webhook_url is empty: Discord alerts WON'T be sent."))
    if ch["telegram"]["enabled"] and not (ch["telegram"]["bot_token"] and ch["telegram"]["chat_id"]):
        out.append(("warning", "Telegram is on but bot_token or chat_id is empty: Telegram alerts WON'T be sent."))
    if ch["sms"]["enabled"] and not all(ch["sms"][k] for k in ("gateway_address", "smtp_user", "smtp_password")):
        out.append(("warning", "SMS is on but gateway_address / smtp_user / smtp_password isn't filled in: texts WON'T be sent."))
    ready, missing = [], []
    for name, r in settings["retailers"].items():
        if not r["enabled"]:
            continue
        if not (r["skus"] or r["urls"]):
            missing.append(f"{name} (no product link or id)")
        elif name == "bestbuy" and not r["api_key"]:
            missing.append("bestbuy (no API key)")
        else:
            ready.append(name)
    out.append(("info", f"retailers ready to poll: {', '.join(ready) or 'none'}"))
    if missing:
        out.append(("warning", f"retailers enabled but NOT usable yet: {', '.join(missing)}. Fix in Settings, or turn them off."))
    feeds = [f["name"] for f in settings["feeds"] if f["enabled"]]
    out.append(("info", f"tracker/news feeds: {', '.join(feeds) or 'none'}"))
    return out
