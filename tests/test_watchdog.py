"""No-poll alerts (grouped, once, with recovery), the blind alert, pause grace, and the startup self-check."""
import asyncio

from shelf_scout import config, db
from shelf_scout.engine import Engine
from shelf_scout.watchdog import Watchdog, startup_check

T0 = 1_000_000.0
MIN = 60


class Recorder:
    name = "rec"

    def __init__(self):
        self.alerts = []

    async def send(self, alert):
        self.alerts.append(alert)

    @property
    def titles(self):
        return [a.notice for a in self.alerts]


def make(tmp_path, ok_at: dict[str, float | None], **settings):
    s = config.validate({"feeds": [], **settings})
    conn = db.connect(tmp_path / "t.db")
    for name, t in ok_at.items():
        conn.execute("INSERT INTO health (retailer,last_ok,error_count,state) VALUES (?,?,?,?)", (name, t, 0, "ok"))
    rec = Recorder()
    engine = Engine(s, conn, [rec], clock=lambda: T0)
    return Watchdog(engine, started=T0 - 3600), engine, conn, rec


def tick(wd, now):
    asyncio.run(wd.tick(now))


def good(conn, name, t):
    conn.execute("UPDATE health SET last_ok=? WHERE retailer=?", (t, name))


def test_one_stale_retailer_gets_one_alert_then_one_recovery(tmp_path):
    wd, engine, conn, rec = make(tmp_path, {"sony": T0, "target": T0})
    tick(wd, T0 + 5 * MIN)
    assert rec.alerts == []
    good(conn, "sony", T0 + 11 * MIN)   # sony keeps working, target doesn't
    tick(wd, T0 + 11 * MIN)
    assert rec.titles == ["shelf-scout can't poll: target"]
    good(conn, "sony", T0 + 20 * MIN)
    tick(wd, T0 + 20 * MIN)
    tick(wd, T0 + 21 * MIN)   # still down: no repeat
    assert len(rec.alerts) == 1
    good(conn, "target", T0 + 22 * MIN)
    good(conn, "sony", T0 + 22 * MIN)
    tick(wd, T0 + 22 * MIN)
    assert rec.titles[-1] == "shelf-scout recovered: target" and len(rec.alerts) == 2


def test_everything_down_is_one_blind_alert_not_one_per_source(tmp_path):
    wd, engine, conn, rec = make(tmp_path, {"sony": T0, "target": T0, "bestbuy": T0})
    tick(wd, T0 + 11 * MIN)
    tick(wd, T0 + 12 * MIN)
    assert rec.titles == ["shelf-scout is BLIND: no source is working"]
    for n in ("sony", "target", "bestbuy"):
        good(conn, n, T0 + 13 * MIN)
    tick(wd, T0 + 13 * MIN)
    assert len(rec.alerts) == 2 and rec.titles[1].startswith("shelf-scout recovered")


def test_threshold_is_the_setting_and_slow_feeds_get_slack(tmp_path):
    feed = {"name": "News", "url": "https://x/rss", "role": "news", "interval_seconds": 900}
    wd, engine, conn, rec = make(tmp_path, {"sony": T0, "News": T0}, no_poll_alert_minutes=3, feeds=[feed])
    good(conn, "News", T0)
    tick(wd, T0 + 4 * MIN)   # sony is past 3 min; the 15-min feed is allowed 3 polls (45 min)
    assert rec.titles == ["shelf-scout can't poll: sony"]


def test_paused_time_and_disabled_sources_dont_count(tmp_path):
    wd, engine, conn, rec = make(tmp_path, {"sony": T0, "walmart": T0}, retailers={"walmart": {"enabled": False}})
    engine.paused = True
    tick(wd, T0 + 60 * MIN)
    assert rec.alerts == []                      # paused: say nothing
    engine.resume()
    engine.resumed_at = T0 + 60 * MIN            # the engine clock is fixed in this test
    tick(wd, T0 + 61 * MIN)
    assert rec.alerts == []                      # the clock restarts at resume; walmart is switched off
    tick(wd, T0 + 72 * MIN)
    assert rec.titles == ["shelf-scout is BLIND: no source is working"]   # sony is the only active source


def test_never_worked_source_counts_from_startup(tmp_path):
    wd, engine, conn, rec = make(tmp_path, {"sony": T0, "amazon": None})
    good(conn, "sony", T0 + 3500)
    tick(wd, T0 + 3500)   # amazon: no good poll since the bot started an hour ago
    assert rec.titles == ["shelf-scout can't poll: amazon"]


def test_startup_check_warns_about_what_will_not_work():
    s = config.validate({"retailers": {"bestbuy": {"skus": ["6525376"]}}})
    msgs = " | ".join(m for _, m in startup_check(s))
    assert "alert_topic is empty" in msgs and "ack_topic is empty" in msgs and "bestbuy (no API key)" in msgs
    assert "gamestop (no product link or id)" in msgs and "retailers ready to poll: sony" in msgs
    ok = config.validate({"channels": {"ntfy": {"alert_topic": "a", "ack_topic": "b"}}})
    assert not any("alert_topic" in m or "ack_topic" in m for _, m in startup_check(ok))
    none = config.validate({"channels": {"ntfy": {"enabled": False}, "pc": {"enabled": False}}})
    assert any("NO notification channel" in m for _, m in startup_check(none))
