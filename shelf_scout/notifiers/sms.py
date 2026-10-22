"""Email-to-SMS through Gmail SMTP. Best effort: unconfigured = skip quietly, loud alerts only."""
import asyncio
import logging
import smtplib
from email.message import EmailMessage

from ..models import Alert
from . import price_only

log = logging.getLogger("shelf_scout.sms")


class Sms:
    name = "sms"

    def __init__(self, cfg: dict):
        self.cfg = cfg

    async def send(self, alert: Alert) -> None:
        if not alert.loud:
            return  # over-cap restocks aren't worth a text
        c = self.cfg
        if not (c["gateway_address"] and c["smtp_user"] and c["smtp_password"]):
            log.info("SMS skipped: not configured")
            return
        r = alert.rows[0]
        # Under ~160 chars so carriers don't split it; the link goes last.
        text = f"{'TEST ' if alert.test else ''}PS5 Pro IN STOCK {r.retailer} {price_only(r.price_cents)} {r.url}"
        msg = EmailMessage()
        msg["From"], msg["To"] = c["smtp_user"], c["gateway_address"]
        msg.set_content(text)
        await asyncio.to_thread(self._smtp_send, msg)

    def _smtp_send(self, msg: EmailMessage) -> None:
        c = self.cfg
        with smtplib.SMTP_SSL(c["smtp_host"], 465, timeout=20) as s:
            s.login(c["smtp_user"], c["smtp_password"])
            s.send_message(msg)
