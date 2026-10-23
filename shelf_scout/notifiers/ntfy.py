"""ntfy: push to the phone, with a tap-to-open link and an Acknowledge button; plus the ack listener."""
import asyncio
import json
import logging

import httpx

from ..models import Alert
from . import body, title

log = logging.getLogger("shelf_scout.ntfy")


class Ntfy:
    name = "ntfy"

    def __init__(self, cfg: dict):
        self.cfg = cfg

    async def send(self, alert: Alert) -> None:
        server, topic, ack_topic = self.cfg["server"].rstrip("/"), self.cfg["alert_topic"], self.cfg["ack_topic"]
        if not topic:
            raise RuntimeError('channels.ntfy.alert_topic is empty in settings.json - set it to your ntfy topic name')
        url = alert.rows[0].url
        actions = [f"view, Open listing, {url}"] if url else []  # empty url (doctor ping) made an illegal trailing-space header
        if alert.loud and ack_topic:
            # The button POSTs "ack:<id>" to the ack topic; ack_listener() below hears it.
            actions.append(f"http, Acknowledge, {server}/{ack_topic}, method=POST, body=ack:{alert.event_id}, clear=true")
        headers = {
            "Title": title(alert),
            "Priority": "urgent" if alert.loud else "low",  # urgent can bypass Do Not Disturb on Android
            "Tags": "rotating_light" if alert.loud else "shopping_cart",
        }
        if url:
            headers["Click"] = url
        if actions:
            headers["Actions"] = "; ".join(actions)
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"{server}/{topic}", content=body(alert).encode(), headers=headers)
            r.raise_for_status()


async def ack_listener(engine) -> None:
    """Listen on the ack topic forever (outbound connection only) and tell the engine about each ack."""
    delay = 1
    while True:
        cfg = engine.settings["channels"]["ntfy"]
        if not (cfg["enabled"] and cfg["ack_topic"]):
            log.info("phone ack is off: channels.ntfy needs enabled=true and a non-empty ack_topic")
            return
        url = f"{cfg['server'].rstrip('/')}/{cfg['ack_topic']}/json?since=2m"  # since: catch an ack sent during a reconnect
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10, read=90)) as c:  # ntfy sends a keepalive every ~45 s
                async with c.stream("GET", url) as r:
                    r.raise_for_status()
                    log.info("listening for phone acks on %s", cfg["ack_topic"])
                    delay = 1
                    async for line in r.aiter_lines():
                        await _handle_line(engine, line)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("ack listener lost its connection (%s: %s); retrying in %ss", type(e).__name__, e, delay)
        await asyncio.sleep(delay)
        delay = min(delay * 2, 60)


async def _handle_line(engine, line: str) -> None:
    try:
        msg = json.loads(line)
    except ValueError:
        return
    text = msg.get("message", "") if msg.get("event") == "message" else ""
    if text.startswith("ack:"):
        try:
            await engine.ack(int(text[4:]))
        except ValueError:
            log.warning("ignored malformed ack message %r", text)
