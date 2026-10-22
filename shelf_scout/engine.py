"""Alert engine: dedupe, loud/quiet tiers, quiet hours, combined alerts, repeat loop, ack."""
import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime

from .config import cap_cents
from .models import Alert, Fulfillment, Layer, Reading, StockState
from .notifiers import build_notifiers, fan_out

log = logging.getLogger("shelf_scout.engine")


def fake_reading(retailer="fakemart", price_cents=89999, **overrides) -> Reading:
    """A believable in-stock Reading for test mode."""
    fields = dict(
        retailer=retailer, state=StockState.IN_STOCK, layer=Layer.PAGE,
        url=f"https://example.com/{retailer}/ps5-pro", price_cents=price_cents,
        seller="Sold by retailer", fulfillment=Fulfillment.SHIP,
        detail="TEST PS5 Pro", at=time.time(),
    )
    fields.update(overrides)
    return Reading(**fields)


def quiet_mode(quiet_hours: list[dict], when: datetime) -> str | None:
    """"mute", "downgrade" or None for this moment. Mute wins if windows overlap."""
    t, day = when.strftime("%H:%M"), when.weekday()  # zero-padded, so string compare = time compare
    modes = set()
    for q in quiet_hours:
        s, e = q["start"], q["end"]
        if s < e:
            hit = day in q["days"] and s <= t < e
        elif s > e:  # overnight: the evening half belongs to the listed day, the morning half to the day after
            hit = (day in q["days"] and t >= s) or ((day - 1) % 7 in q["days"] and t < e)
        else:
            hit = False
        if hit:
            modes.add(q["mode"])
    return "mute" if "mute" in modes else "downgrade" if modes else None


@dataclass
class _Event:
    id: int
    reading: Reading
    loud: bool
    test: bool
    acked: bool = False
    notified: bool = False  # has any alert included this event yet?


class Engine:
    def __init__(self, settings: dict, conn, notifiers=None, clock=time.time):
        self.settings = settings  # replace this dict to apply new settings live
        self.conn = conn
        self._notifiers = notifiers  # None = build from settings on every send
        self._clock = clock
        self._open: dict[tuple[str, str], _Event] = {}  # one open event per (retailer, listing url)
        self._repeat: asyncio.Task | None = None
        self._last_alert_ids: set[int] = set()  # events in the most recent alert; one Ack covers them all

    # ---- readings in -----------------------------------------------------------------------

    async def handle_reading(self, r: Reading, test: bool = False) -> None:
        key = (r.retailer, r.url)
        if r.state is StockState.ERROR:
            return  # unknown is not "out of stock": leave any open event exactly as it is
        ev = self._open.get(key)
        if r.state is StockState.OUT_OF_STOCK:
            if ev:
                del self._open[key]
                self.conn.execute("UPDATE events SET ended=? WHERE id=?", (r.at, ev.id))
                self.conn.commit()
                log.info("event %s closed: %s is out of stock again", ev.id, r.retailer)
                self._stop_repeat_if_done()
            return
        if ev:
            return  # still in stock: dedupe, no new alert
        # Unknown price counts as loud: better a false alarm than a missed drop.
        loud = r.price_cents is None or r.price_cents <= cap_cents(self.settings)
        cur = self.conn.execute("INSERT INTO events (retailer, started, price_cents, seller) VALUES (?,?,?,?)",
                                (r.retailer, r.at, r.price_cents, r.seller))
        self.conn.commit()
        ev = self._open[key] = _Event(cur.lastrowid, r, loud, test)
        log.info("event %s opened: %s in stock at %s (%s)", ev.id, r.retailer, r.price_cents, "LOUD" if loud else "quiet")
        await self._dispatch()

    async def notice(self, title: str, detail: str, url: str = "") -> None:
        """Tell the owner something about the bot itself (e.g. a retailer is blocking us). Quiet, sent once, no repeat."""
        row = Reading("bot", StockState.ERROR, Layer.PAGE, url, None, None, None, detail, self._clock())
        alert = Alert(event_id=0, loud=False, rows=[row], msrp_cents=self.settings["msrp_cents"], notice=title)
        await fan_out(self._notifiers if self._notifiers is not None else build_notifiers(self.settings), alert)

    # ---- ack -------------------------------------------------------------------------------

    async def ack(self, event_id: int | None = None) -> None:
        """Stop repeats for one event (and everything in the same alert), or for all if None."""
        if event_id is None:
            ids = {e.id for e in self._open.values()}
        else:
            ids = {event_id} | (self._last_alert_ids if event_id in self._last_alert_ids else set())
        for e in self._open.values():
            if e.id in ids:
                e.acked = True
        self.conn.executemany("UPDATE events SET acked_at=? WHERE id=? AND acked_at IS NULL",
                              [(self._clock(), i) for i in ids])
        self.conn.commit()
        log.info("acknowledged event(s) %s", sorted(ids))
        self._stop_repeat_if_done()

    # ---- sending ---------------------------------------------------------------------------

    def _pending(self) -> list[_Event]:
        """Unacked open events, cheapest first, unknown price last, then earliest detection."""
        evs = [e for e in self._open.values() if not e.acked]
        return sorted(evs, key=lambda e: (e.reading.price_cents is None, e.reading.price_cents or 0, e.reading.at))

    def _loud_pending(self) -> bool:
        return any(e.loud for e in self._pending())

    async def _dispatch(self, tick: bool = False) -> None:
        """tick=False: a new event arrived. tick=True: the repeat timer fired."""
        pending = self._pending()
        loud_pending = any(e.loud for e in pending)
        fresh = [e for e in pending if not e.notified]
        s = self.settings
        mode = quiet_mode(s["quiet_hours"], datetime.fromtimestamp(self._clock()))
        if mode and loud_pending and s["quiet_hours_loud_override"]:
            mode = None

        if mode == "mute":
            for e in fresh:
                e.notified = True  # muted means dropped; loud ones still repeat once the window ends
        elif mode == "downgrade":
            if fresh and not tick:
                await self._send(fresh, loud=False)
        elif tick:
            if loud_pending:
                await self._send(pending, loud=True)
        elif fresh:
            # A new event while others are still unacked goes out together, as one ranked alert.
            await self._send(pending if loud_pending else fresh, loud=loud_pending)
        if loud_pending and (self._repeat is None or self._repeat.done()):
            self._repeat = asyncio.create_task(self._repeat_loop())

    async def _send(self, events: list[_Event], loud: bool) -> None:
        for e in events:
            e.notified = True
        self._last_alert_ids = {e.id for e in events}
        alert = Alert(event_id=events[0].id, loud=loud, rows=[e.reading for e in events],
                      test=any(e.test for e in events), msrp_cents=self.settings["msrp_cents"])
        await fan_out(self._notifiers if self._notifiers is not None else build_notifiers(self.settings), alert)

    async def _repeat_loop(self) -> None:
        me = asyncio.current_task()
        try:
            while True:
                await asyncio.sleep(self.settings["repeat_seconds"])
                if not self._loud_pending():
                    return
                await self._dispatch(tick=True)
        except Exception:
            log.exception("repeat loop crashed; alerts for the current event(s) will not repeat")
        finally:
            if self._repeat is me:
                self._repeat = None

    def _stop_repeat_if_done(self) -> None:
        if self._repeat and not self._loud_pending():
            self._repeat.cancel()
            self._repeat = None

    async def wait_idle(self) -> None:
        """Return once nothing loud is waiting for an ack (used by test mode)."""
        while self._loud_pending():
            await asyncio.sleep(0.5)
