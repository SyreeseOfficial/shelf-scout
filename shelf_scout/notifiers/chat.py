"""Discord webhook and Telegram bot. Quiet alerts are sent without a ping/notification sound."""
import httpx

from ..models import Alert
from . import body, title


def _text(alert: Alert) -> str:
    return f"{title(alert)}\n\n{body(alert)}"


class Discord:
    name = "discord"

    def __init__(self, cfg: dict):
        self.cfg = cfg

    async def send(self, alert: Alert) -> None:
        if not self.cfg["webhook_url"]:
            raise RuntimeError("channels.discord.webhook_url is empty in settings.json")
        payload = {"content": _text(alert)[:2000]}  # Discord's message limit
        if not alert.loud:
            payload["flags"] = 4096  # SUPPRESS_NOTIFICATIONS
        async with httpx.AsyncClient(timeout=15) as c:
            (await c.post(self.cfg["webhook_url"], json=payload)).raise_for_status()


class Telegram:
    name = "telegram"

    def __init__(self, cfg: dict):
        self.cfg = cfg

    async def send(self, alert: Alert) -> None:
        if not (self.cfg["bot_token"] and self.cfg["chat_id"]):
            raise RuntimeError("channels.telegram needs both bot_token and chat_id in settings.json")
        url = f"https://api.telegram.org/bot{self.cfg['bot_token']}/sendMessage"
        payload = {"chat_id": self.cfg["chat_id"], "text": _text(alert), "disable_notification": not alert.loud}
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(url, json=payload)
            if r.status_code >= 400:  # don't print the URL: it contains the bot token
                raise RuntimeError(f"Telegram rejected the message (HTTP {r.status_code}): {r.text[:200]}")
