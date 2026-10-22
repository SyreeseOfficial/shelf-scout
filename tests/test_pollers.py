"""Parser tests (in / out / garbage / blocked per retailer) and the back-off runner.

Fixtures: tests/fixtures/sony/*.json and amazon/blocked.html are real captures. bestbuy/* and
amazon/in_stock|out_of_stock are hand-written (live reads are blocked), so they prove the parser
logic, not that the live site still looks like this.
"""
import asyncio
from pathlib import Path

import httpx
import pytest

from shelf_scout import config, db
from shelf_scout.engine import Engine
from shelf_scout.models import Fulfillment, Layer, StockState
from shelf_scout.pollers import Blocked, ParseError, PollError, Poller, RunState, poll_step, raise_if_blocked, to_cents
from shelf_scout.pollers import amazon, bestbuy, sony

FIX = Path(__file__).parent / "fixtures"
URL = "https://example.com/ps5"


def read(path: str) -> str:
    return (FIX / path).read_text()


# ---- sony ----------------------------------------------------------------------------------

def test_sony_out_of_stock():
    [r] = sony.parse(read("sony/out_of_stock.json"), {"1000050928": URL})
    assert (r.state, r.price_cents, r.layer, r.fulfillment) == (StockState.OUT_OF_STOCK, 89900, Layer.ENDPOINT, Fulfillment.SHIP)


def test_sony_in_stock():
    [r] = sony.parse(read("sony/in_stock.json"), {"1000041051": URL})
    assert (r.state, r.price_cents) == (StockState.IN_STOCK, 7900)


def test_sony_garbage_is_parse_error_not_out_of_stock():
    for bad in (read("sony/garbage.json"), "<html>not json</html>", ""):
        with pytest.raises(ParseError):
            sony.parse(bad, {"1000050928": URL})


def test_sony_missing_sku_and_unknown_status_are_errors():
    [r] = sony.parse(read("sony/in_stock.json"), {"9999999999": URL})  # asked for a sku the reply doesn't have
    assert r.state is StockState.ERROR and "9999999999" in r.detail
    weird = read("sony/in_stock.json").replace("inStock", "comingSoon")
    [r] = sony.parse(weird, {"1000041051": URL})
    assert r.state is StockState.ERROR


# ---- best buy ------------------------------------------------------------------------------

def test_bestbuy_in_and_out():
    [r] = bestbuy.parse(read("bestbuy/in_stock.json"), "6525376", URL)
    assert (r.state, r.price_cents) == (StockState.IN_STOCK, 89999)
    [r] = bestbuy.parse(read("bestbuy/out_of_stock.json"), "6525376", URL)
    assert r.state is StockState.OUT_OF_STOCK


def test_bestbuy_garbage_is_parse_error():
    for bad in (read("bestbuy/garbage.json"), "<html>nope</html>", '{"onlineAvailability": "yes"}'):
        with pytest.raises(ParseError):
            bestbuy.parse(bad, "6525376", URL)


# ---- amazon --------------------------------------------------------------------------------

def test_amazon_in_stock_reads_price_and_seller():
    [r] = amazon.parse(read("amazon/in_stock.html"), URL)
    assert r.state is StockState.IN_STOCK and r.price_cents == 89999
    assert "Sold by" not in r.seller and "Amazon.com" in r.seller


def test_amazon_out_of_stock():
    [r] = amazon.parse(read("amazon/out_of_stock.html"), URL)
    assert r.state is StockState.OUT_OF_STOCK


def test_amazon_garbage_and_challenge_page_are_not_out_of_stock():
    for page in ("garbage.html", "blocked.html"):
        with pytest.raises(ParseError):
            amazon.parse(read(f"amazon/{page}"), URL)


# ---- block detection -----------------------------------------------------------------------

def response(status=200, text="", ctype="text/html", url="https://shop.example.com/p"):
    return httpx.Response(status, text=text, headers={"content-type": ctype}, request=httpx.Request("GET", url))


@pytest.mark.parametrize("r", [
    response(429), response(403), response(503),
    response(200, read("amazon/blocked.html")),  # the real Amazon challenge page: HTTP 200!
    response(200, "<title>Access Denied</title>"),
    response(200, "ok", url="https://shop.example.com/captcha?x=1"),
])
def test_blocks_are_detected(r):
    with pytest.raises(Blocked):
        raise_if_blocked(r)


def test_normal_pages_are_not_blocks():
    raise_if_blocked(response(200, read("amazon/in_stock.html")))
    raise_if_blocked(response(200, read("sony/out_of_stock.json"), ctype="application/json"))


def test_to_cents():
    assert to_cents("$1,049.99") == 104999 and to_cents(899.99) == 89999 and to_cents(899.0) == 89900
    with pytest.raises(ParseError):
        to_cents("call us")


# ---- runner: back-off, one notification, recovery ------------------------------------------

class Scripted(Poller):
    """Returns/raises whatever is queued, one item per poll."""
    retailer, layer = "fake", Layer.PAGE

    def __init__(self, script, settings):
        super().__init__(None, lambda: settings)
        self.script = list(script)

    async def check(self):
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class Recorder:
    name = "rec"

    def __init__(self):
        self.alerts = []

    async def send(self, alert):
        self.alerts.append(alert)


def make(tmp_path, script):
    settings = config.validate({"retailers": {"fake": {"interval_seconds": 60}}})
    rec = Recorder()
    conn = db.connect(tmp_path / "t.db")
    return Scripted(script, settings), Engine(settings, conn, [rec]), conn, rec


def step(poller, engine, conn, st):
    return asyncio.run(poll_step(poller, engine, conn, st))


def test_block_backs_off_notifies_once_and_recovers(tmp_path):
    from shelf_scout.engine import fake_reading
    good = [fake_reading("fake", state=StockState.OUT_OF_STOCK)]
    poller, engine, conn, rec = make(tmp_path, [Blocked("HTTP 429")] * 3 + [good])
    st = RunState()
    waits = [step(poller, engine, conn, st) for _ in range(3)]
    # 120 s, 240 s, 480 s, each within the +/-20% jitter
    assert [round(w / b) for w, b in zip(waits, (120, 240, 480))] == [1, 1, 1]
    assert waits[1] > waits[0] * 1.4 and waits[2] > waits[1] * 1.4
    assert len(rec.alerts) == 1 and "blocking" in rec.alerts[0].notice  # one notice for three blocked polls
    row = conn.execute("SELECT * FROM health WHERE retailer='fake'").fetchone()
    assert (row["state"], row["error_count"], row["last_ok"]) == ("blocked", 3, None)

    wait = step(poller, engine, conn, st)  # recovery
    assert 48 <= wait <= 72 and st.fails == 0 and not st.blocked
    row = conn.execute("SELECT * FROM health WHERE retailer='fake'").fetchone()
    assert (row["state"], row["error_count"]) == ("ok", 0) and row["last_ok"]


def test_backoff_caps_at_30_minutes(tmp_path):
    poller, engine, conn, _ = make(tmp_path, [Blocked("x")] * 12)
    waits = [step(poller, engine, conn, RunState(fails=10 + i)) for i in range(2)]
    assert all(1800 * 0.8 <= w <= 1800 * 1.2 for w in waits)


def test_error_never_closes_an_open_event(tmp_path):
    from shelf_scout.engine import fake_reading
    poller, engine, conn, rec = make(tmp_path, [[fake_reading("fake")], ParseError("page changed")])
    st = RunState()
    step(poller, engine, conn, st)  # in stock: alert
    step(poller, engine, conn, st)  # then the page becomes unreadable
    assert conn.execute("SELECT ended FROM events").fetchone()["ended"] is None  # still open, not "sold out"
    assert len(rec.alerts) == 1  # and a non-block error sends no notice


def test_crashing_poller_is_contained(tmp_path):
    poller, engine, conn, _ = make(tmp_path, [RuntimeError("bug")])
    wait = step(poller, engine, conn, RunState())
    assert wait > 60
    assert "bug" in conn.execute("SELECT note FROM health").fetchone()["note"]


def test_readings_table_holds_latest_snapshot(tmp_path):
    from shelf_scout.engine import fake_reading
    poller, engine, conn, _ = make(tmp_path, [[fake_reading("fake")], ParseError("oops")])
    st = RunState()
    step(poller, engine, conn, st)
    assert [r["state"] for r in conn.execute("SELECT state FROM readings")] == ["in_stock"]
    step(poller, engine, conn, st)
    assert [r["state"] for r in conn.execute("SELECT state FROM readings")] == ["error"]  # replaced, no stale row
