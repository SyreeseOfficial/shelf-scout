"""Notifier protocol, alert formatting shared by every channel, and the fan-out."""
import asyncio
import logging
from typing import Protocol

from ..models import Alert, Reading

log = logging.getLogger("shelf_scout.notify")


class Notifier(Protocol):
    name: str

    async def send(self, alert: Alert) -> None:
        """Must raise on failure; fan_out() catches and logs it."""


def money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def price_only(cents: int | None) -> str:
    return "price unknown" if cents is None else money(cents)


def price_label(cents: int | None, msrp: int) -> str:
    if cents is None:
        return "price unknown"  # speed over accuracy: we still alert when the price isn't readable
    diff = cents - msrp
    if diff == 0:
        return f"{money(cents)}, at MSRP"
    return f"{money(cents)}, {'+' if diff > 0 else '-'}{money(abs(diff)).removesuffix('.00')}"


def row_text(r: Reading, msrp: int) -> str:
    """One line per retailer: who, price vs MSRP, seller, how it ships, how we saw it, link."""
    who = f"{r.retailer} ({r.detail})" if r.detail else r.retailer
    parts = [price_label(r.price_cents, msrp), r.seller or "seller unknown",
             r.fulfillment.value if r.fulfillment else "fulfillment unknown", f"via {r.layer.value}"]
    return f"{who}: " + " | ".join(parts) + f"\n{r.url}"


def title(alert: Alert) -> str:
    first = alert.rows[0]
    more = f" (+{len(alert.rows) - 1} more)" if len(alert.rows) > 1 else ""
    what = "PS5 Pro IN STOCK" if alert.loud else "PS5 Pro in stock, over price cap"
    return f"{'[TEST] ' if alert.test else ''}{what} - {first.retailer} {price_only(first.price_cents)}{more}"


def body(alert: Alert) -> str:
    return "\n\n".join(row_text(r, alert.msrp_cents) for r in alert.rows)


async def fan_out(notifiers: list[Notifier], alert: Alert) -> None:
    """Send to every channel at once. One broken channel never blocks the others."""
    results = await asyncio.gather(*(n.send(alert) for n in notifiers), return_exceptions=True)
    for n, res in zip(notifiers, results):
        if isinstance(res, Exception):
            log.error("channel %s FAILED to send: %s: %s", n.name, type(res).__name__, res)
        else:
            log.info("channel %s sent (%s)", n.name, "loud" if alert.loud else "quiet")


def build_notifiers(settings: dict) -> list[Notifier]:
    """Enabled channels only. Built per send so settings changes apply without a restart."""
    from .chat import Discord, Telegram  # imported here: these modules import the helpers above
    from .ntfy import Ntfy
    from .pc import Pc
    from .sms import Sms
    ch = settings["channels"]
    classes = {"ntfy": Ntfy, "discord": Discord, "telegram": Telegram, "sms": Sms, "pc": Pc}
    return [cls(ch[name]) for name, cls in classes.items() if ch[name]["enabled"]]
