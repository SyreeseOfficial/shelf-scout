"""Dashboard + settings UI, driven through the real ASGI app (same thread as the DB, like the live service)."""
import asyncio
import json
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx

from shelf_scout import config, db
from shelf_scout.engine import Engine, fake_reading
from shelf_scout.models import StockState
from shelf_scout.web.app import build_settings, create_app


class Recorder:
    name = "rec"

    def __init__(self):
        self.alerts = []

    async def send(self, alert):
        self.alerts.append(alert)


def with_app(tmp_path, scenario, **settings):
    """Run `scenario(client, engine, conn, rec, settings_path)` against a fresh app."""
    path = tmp_path / "settings.json"
    s = config.validate(settings)
    conn = db.connect(tmp_path / "t.db")
    rec = Recorder()
    engine = Engine(s, conn, [rec])
    app = create_app(engine, conn, path)

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765") as client:
            return await scenario(client, engine, conn, rec, path)

    return asyncio.run(go())


def form_for(engine, **changes):
    """What the browser would post if the owner just pressed Save, plus `changes`."""
    cur = engine.settings
    f = {"msrp_cents": f"{cur['msrp_cents'] / 100:.2f}", "tolerance_cents": f"{cur['tolerance_cents'] / 100:.2f}"}
    for k, v in cur.items():
        if not isinstance(v, (dict, list)) and k not in f:   # the two money keys are already in dollars
            f[k] = str(v)
    for sect, prefix in (("retailers", "r_"), ("channels", "c_"), ("dashboard", "d_")):
        groups = {"": cur[sect]} if sect == "dashboard" else cur[sect]
        for name, c in groups.items():
            for k, v in c.items():
                key = f"{prefix}{k}" if sect == "dashboard" else f"{prefix}{name}_{k}"
                if isinstance(v, bool):
                    if v:
                        f[key] = "on"
                elif isinstance(v, list):
                    f[key] = "\n".join(v)
                else:
                    f[key] = str(v)
    for i, fd in enumerate(cur["feeds"]):
        f.update({f"f{i}_name": fd["name"], f"f{i}_url": fd["url"], f"f{i}_role": fd["role"], f"f{i}_interval": str(fd["interval_seconds"])})
        if fd["enabled"]:
            f[f"f{i}_enabled"] = "on"
    for k in ("quiet_hours_loud_override", "announcement_heads_up"):
        f.pop(k, None) if not cur[k] else f.__setitem__(k, "on")
    f.update(changes)
    return f


def post(client, form):
    return client.post("/settings", content=urlencode(form), headers={"content-type": "application/x-www-form-urlencoded"})


def test_dashboard_panels_render_with_real_data(tmp_path):
    async def scenario(client, engine, conn, rec, path):
        await engine.handle_reading(fake_reading("sony", price_cents=89999))
        conn.execute("INSERT INTO health (retailer,last_ok,error_count,state,note) VALUES ('amazon',NULL,3,'blocked','blocked: bot check')")
        conn.execute("INSERT INTO readings (retailer,url,layer,detail,state,at) VALUES ('target','https://t/x','endpoint','Lynnwood store','out_of_stock',?)", (time.time(),))
        html = (await client.get("/")).text
        for needle in ("Live stock", "Bot health", "Restock history", "Upcoming events", "Acknowledge", "Stop everything", "Test alert",
                       "waiting for acknowledgement", "Blocked, backing off", "Out of stock", "Lynnwood store", "Black Friday"):
            assert needle in html, needle
        assert "sony" in html and "$899.99, at MSRP" in html
        assert (await client.get("/partial/status")).status_code == 200
    with_app(tmp_path, scenario)


def test_changing_tolerance_in_the_ui_changes_the_next_alert_tier_without_restart(tmp_path):
    async def scenario(client, engine, conn, rec, path):
        r = fake_reading("a", price_cents=94999 + 3000)   # $30 over the default $949.99 cap
        await engine.handle_reading(r)
        assert rec.alerts[-1].loud is False
        await engine.handle_reading(fake_reading("a", price_cents=94999 + 3000, state=StockState.OUT_OF_STOCK))
        resp = await post(client, form_for(engine, tolerance_cents="100.00"))   # cap is now $999.99
        assert resp.status_code == 303 and json.loads(path.read_text())["tolerance_cents"] == 10000
        await engine.handle_reading(r)
        assert rec.alerts[-1].loud is True
        engine._repeat and engine._repeat.cancel()
    with_app(tmp_path, scenario)


def test_bad_values_are_rejected_with_a_message_naming_the_setting_and_nothing_is_saved(tmp_path):
    async def scenario(client, engine, conn, rec, path):
        resp = await post(client, form_for(engine, r_sony_interval_seconds="abc"))
        assert resp.status_code == 200 and "retailers.sony.interval_seconds" in resp.text and "Not saved" in resp.text
        assert "abc" in resp.text and not path.exists() and engine.settings["retailers"]["sony"]["interval_seconds"] == 45
        resp = await post(client, form_for(engine, msrp_cents="lots"))
        assert "MSRP must be a dollar amount" in resp.text
        resp = await post(client, form_for(engine, r_sony_interval_seconds="2"))   # below the minimum
        assert "at least" in resp.text
    with_app(tmp_path, scenario)


def test_secrets_are_masked_blank_means_unchanged_and_new_value_replaces(tmp_path):
    async def scenario(client, engine, conn, rec, path):
        page = (await client.get("/settings")).text
        assert "super-secret-topic-1234" not in page and "(…1234)" in page
        resp = await post(client, form_for(engine, c_ntfy_alert_topic=""))
        assert resp.status_code == 303 and engine.settings["channels"]["ntfy"]["alert_topic"] == "super-secret-topic-1234"
        await post(client, form_for(engine, c_ntfy_alert_topic="another-topic-9999"))
        assert engine.settings["channels"]["ntfy"]["alert_topic"] == "another-topic-9999"
    with_app(tmp_path, scenario, channels={"ntfy": {"alert_topic": "super-secret-topic-1234"}})


def test_quiet_hours_and_feed_editors_add_and_remove_rows(tmp_path):
    async def scenario(client, engine, conn, rec, path):
        form = form_for(engine, q0_start="23:00", q0_end="07:00", q0_mode="downgrade", f3_name="My feed", f3_url="https://x.example/rss", f3_role="news", f3_interval="120")
        form.update({f"q0_day{d}": "on" for d in range(7)})
        assert (await post(client, form)).status_code == 303
        s = engine.settings
        assert s["quiet_hours"] == [{"days": list(range(7)), "start": "23:00", "end": "07:00", "mode": "downgrade"}]
        assert s["feeds"][-1]["name"] == "My feed" and s["feeds"][-1]["role"] == "news" and s["feeds"][-1]["interval_seconds"] == 120
        f = form_for(engine, q0_remove="on", f0_remove="on")   # remove the window and the first feed
        await post(client, f)
        assert engine.settings["quiet_hours"] == [] and "My feed" in [x["name"] for x in engine.settings["feeds"]]
        assert "Reddit r/consoledeals" not in [x["name"] for x in engine.settings["feeds"]]
        page = (await client.get("/settings")).text
        assert "Quiet hours" in page and "My feed" in page
    with_app(tmp_path, scenario)


def test_stop_everything_pauses_repeats_and_resume_restores_them(tmp_path):
    async def scenario(client, engine, conn, rec, path):
        await engine.handle_reading(fake_reading("a"))
        assert engine._repeat and not engine._repeat.done()
        assert (await client.post("/api/pause")).json() == {"ok": True}
        await asyncio.sleep(0)
        assert engine.paused and engine._repeat is None
        assert "STOPPED" in (await client.get("/")).text
        await client.post("/api/resume")
        assert not engine.paused and engine._repeat is not None
        await client.post("/api/ack")
        assert engine.waiting == 0 and engine._repeat is None
        assert (await client.post("/api/nonsense")).status_code == 404
    with_app(tmp_path, scenario)


def test_test_button_runs_the_real_pipeline_and_cleans_up_after_ack(tmp_path):
    async def scenario(client, engine, conn, rec, path):
        await client.post("/api/test-quiet")
        await asyncio.sleep(0.1)
        assert len(rec.alerts) == 1 and rec.alerts[0].test and not rec.alerts[0].loud
        await client.post("/api/test")
        await asyncio.sleep(0.1)
        assert rec.alerts[-1].loud and engine.waiting == 1
        await client.post("/api/ack")
        await asyncio.sleep(1)   # fire_test notices the ack (it checks every 0.5 s) and closes the fake event
        assert not engine._open
    with_app(tmp_path, scenario)


def test_posts_from_another_website_are_refused(tmp_path):
    async def scenario(client, engine, conn, rec, path):
        evil = {"origin": "https://evil.example", "content-type": "application/x-www-form-urlencoded"}
        assert (await client.post("/settings", content=urlencode(form_for(engine, c_discord_webhook_url="https://evil.example/hook")), headers=evil)).status_code == 403
        assert (await client.post("/api/pause", headers=evil)).status_code == 403 and not engine.paused
        ok = {"origin": "http://127.0.0.1:8765"}
        assert (await client.post("/api/pause", headers=ok)).status_code == 200
    with_app(tmp_path, scenario)


def test_build_settings_roundtrip_is_a_no_op():
    cur = config.validate({})
    class E: settings = cur
    assert config.validate(build_settings(form_for(E), cur)) == cur
