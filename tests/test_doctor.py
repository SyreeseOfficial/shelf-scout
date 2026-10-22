"""Doctor checks, with fake channels and a fake network (httpx.MockTransport)."""
import asyncio

import httpx

from shelf_scout import config
from shelf_scout.doctor import Check, check_ack_topic, check_channels, check_sources, report, run_doctor


class Good:
    name = "good"

    def __init__(self):
        self.sent = []

    async def send(self, alert):
        self.sent.append(alert)


class Bad:
    name = "bad"

    async def send(self, alert):
        raise RuntimeError("webhook returned 404")


def client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_channel_ping_reports_each_channel_separately():
    good = Good()
    checks = asyncio.run(check_channels(config.validate({}), [good, Bad()]))
    assert [(c.ok, c.name) for c in checks] == [(True, "channel good sends"), (False, "channel bad sends")]
    assert "404" in checks[1].detail and "Fix" in checks[1].detail
    assert good.sent[0].notice.startswith("shelf-scout doctor") and not good.sent[0].loud


def test_no_channels_is_a_failure_with_a_fix():
    [c] = asyncio.run(check_channels(config.validate({}), []))
    assert not c.ok and "turn one on" in c.detail


def test_ack_topic_checks():
    s = config.validate({"channels": {"ntfy": {"ack_topic": "ack-abc"}}})
    seen = []

    async def go(handler, settings):
        async with client(handler) as c:
            return await check_ack_topic(settings, c)

    ok = asyncio.run(go(lambda r: (seen.append(str(r.url)), httpx.Response(200, text=""))[1], s))
    assert ok.ok and "ack-abc/json" in seen[0]
    assert not asyncio.run(go(lambda r: httpx.Response(404), s)).ok
    assert not asyncio.run(go(lambda r: httpx.Response(200), config.validate({}))).ok   # topic not set
    assert asyncio.run(go(lambda r: httpx.Response(500), config.validate({"channels": {"ntfy": {"enabled": False}}}))).ok


def test_sources_pass_fail_with_plain_fixes():
    s = config.validate({"feeds": [{"name": "F", "url": "https://f.example/rss"}],
                         "retailers": {r: {"enabled": r in ("sony", "gamestop")} for r in config.RETAILERS}})
    sony_ok = '{"products":[{"code":"1000050928","name":"PS5 Pro","stock":{"stockLevelStatus":"outOfStock"},"price":{"value":899.0}}]}'

    def handler(r):
        if "playstation.com" in r.url.host:
            return httpx.Response(200, text=sony_ok, headers={"content-type": "application/json"})
        return httpx.Response(200, text="<html>not a feed</html>", headers={"content-type": "text/html"})

    async def go():
        async with client(handler) as c:
            return await check_sources(s, c)

    by_name = {c.name: c for c in asyncio.run(go())}
    assert by_name["retailer sony readable"].ok
    assert not by_name["retailer gamestop readable"].ok and "Settings" in by_name["retailer gamestop readable"].detail
    assert not by_name["feed F readable"].ok and "RSS" in by_name["feed F readable"].detail


def test_run_doctor_uses_given_channels_and_report_exit_code(tmp_path, capsys, monkeypatch):
    s = config.validate({"retailers": {r: {"enabled": False} for r in config.RETAILERS}, "feeds": [],
                         "channels": {"ntfy": {"enabled": False}}})
    results = asyncio.run(run_doctor(s, tmp_path / "t.db", notifiers=[Good()], check_systemd=False))
    assert all(c.ok for c in results) and report(results) == 0
    assert report([Check(False, "x", "broken. Fix: do y")]) == 1
    assert "[FAIL] x: broken. Fix: do y" in capsys.readouterr().out
