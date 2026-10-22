import asyncio
import dataclasses
from datetime import datetime

from shelf_scout import config, db
from shelf_scout.engine import Engine, fake_reading, quiet_mode
from shelf_scout.models import StockState

MON, SUN = 5, 11  # Jan 5 and Jan 11, 2026 are a Monday and a Sunday


class Recorder:
    name = "rec"

    def __init__(self):
        self.alerts = []

    async def send(self, alert):
        self.alerts.append(alert)


class Broken:
    name = "broken"

    async def send(self, alert):
        raise RuntimeError("boom")


def make(tmp_path, notifiers=None, now=None, **overrides):
    settings = {**config.validate({}), **overrides}
    rec = Recorder()
    engine = Engine(settings, db.connect(tmp_path / "t.db"), [rec] if notifiers is None else notifiers + [rec],
                    clock=lambda: now or datetime(2026, 1, MON, 12, 0).timestamp())
    return engine, rec


def run(coro):
    return asyncio.run(coro)


def out(r):
    return dataclasses.replace(r, state=StockState.OUT_OF_STOCK)


def test_dedupe_and_rearm(tmp_path):
    engine, rec = make(tmp_path)
    r = fake_reading()

    async def go():
        await engine.handle_reading(r)
        await engine.handle_reading(r)  # still in stock: no second alert
        await engine.handle_reading(dataclasses.replace(r, state=StockState.ERROR))  # unknown: changes nothing
        await engine.handle_reading(r)
        assert len(rec.alerts) == 1
        await engine.handle_reading(out(r))
        await engine.handle_reading(r)  # out and back = new event
        assert len(rec.alerts) == 2
        assert engine.conn.execute("SELECT COUNT(*) FROM events WHERE ended IS NOT NULL").fetchone()[0] == 1
        await engine.ack()

    run(go())


def test_tier_boundary(tmp_path):
    engine, rec = make(tmp_path)
    cap = config.cap_cents(engine.settings)

    async def go():
        await engine.handle_reading(fake_reading("a", cap))
        await engine.handle_reading(fake_reading("b", cap + 1))
        await engine.handle_reading(fake_reading("c", None))
        await engine.ack()

    run(go())
    assert rec.alerts[0].loud  # == cap is loud
    assert rec.alerts[1].loud  # b was quiet but a is still unacked, so it joins the loud alert
    assert rec.alerts[2].loud  # unknown price is loud


def test_over_cap_alone_is_quiet_and_never_repeats(tmp_path):
    engine, rec = make(tmp_path, repeat_seconds=0.05)

    async def go():
        await engine.handle_reading(fake_reading(price_cents=config.cap_cents(engine.settings) + 1))
        await asyncio.sleep(0.2)

    run(go())
    assert len(rec.alerts) == 1 and not rec.alerts[0].loud


def test_combine_ranks_cheapest_first(tmp_path):
    engine, rec = make(tmp_path)

    async def go():
        await engine.handle_reading(fake_reading("pricey", 93000))
        await engine.handle_reading(fake_reading("cheap", 89999))
        await engine.ack()

    run(go())
    assert [r.retailer for r in rec.alerts[1].rows] == ["cheap", "pricey"]


def test_repeats_until_acked(tmp_path):
    engine, rec = make(tmp_path, repeat_seconds=0.05)

    async def go():
        await engine.handle_reading(fake_reading())
        await asyncio.sleep(0.28)
        n = len(rec.alerts)
        assert n >= 3
        await engine.ack(rec.alerts[0].event_id)
        await asyncio.sleep(0.2)
        assert len(rec.alerts) == n  # silence after the ack
        assert engine.conn.execute("SELECT acked_at FROM events").fetchone()[0] is not None

    run(go())


def test_one_ack_covers_a_combined_alert(tmp_path):
    engine, rec = make(tmp_path, repeat_seconds=0.05)

    async def go():
        await engine.handle_reading(fake_reading("a", 89999))
        await engine.handle_reading(fake_reading("b", 90000))
        await engine.ack(rec.alerts[-1].event_id)
        n = len(rec.alerts)
        await asyncio.sleep(0.2)
        assert len(rec.alerts) == n

    run(go())


def test_failing_channel_does_not_block_others(tmp_path):
    engine, rec = make(tmp_path, notifiers=[Broken()])
    run(engine.handle_reading(fake_reading()))
    assert len(rec.alerts) == 1


def test_quiet_hours_overnight_and_empty():
    night = [{"days": [4], "start": "23:00", "end": "07:00", "mode": "mute"}]  # Fridays, spilling into Saturday
    assert quiet_mode(night, datetime(2026, 1, 9, 23, 30)) == "mute"  # Fri 23:30
    assert quiet_mode(night, datetime(2026, 1, 10, 6, 59)) == "mute"  # Sat 06:59
    assert quiet_mode(night, datetime(2026, 1, 10, 7, 0)) is None  # window over
    assert quiet_mode(night, datetime(2026, 1, 10, 23, 30)) is None  # Saturday night isn't listed
    assert quiet_mode(night, datetime(2026, 1, 9, 12, 0)) is None
    assert quiet_mode([], datetime(2026, 1, 9, 23, 30)) is None


def test_mute_and_downgrade_and_override(tmp_path):
    late = datetime(2026, 1, MON, 23, 30).timestamp()
    window = lambda mode: [{"days": [0], "start": "23:00", "end": "07:00", "mode": mode}]

    engine, rec = make(tmp_path, now=late, quiet_hours=window("mute"))
    run(engine.handle_reading(fake_reading()))
    assert rec.alerts == []

    (tmp_path / "t.db").unlink()
    engine, rec = make(tmp_path, now=late, quiet_hours=window("downgrade"))
    run(engine.handle_reading(fake_reading()))
    assert len(rec.alerts) == 1 and not rec.alerts[0].loud

    (tmp_path / "t.db").unlink()
    engine, rec = make(tmp_path, now=late, quiet_hours=window("mute"), quiet_hours_loud_override=True)

    async def go():
        await engine.handle_reading(fake_reading())
        await engine.ack()

    run(go())
    assert len(rec.alerts) == 1 and rec.alerts[0].loud
