"""eBay poller. tests/fixtures/ebay/search.json is hand-written from the Browse API docs (no key yet to capture a real reply)."""
import asyncio
import json
from pathlib import Path

import httpx
import pytest

from shelf_scout import config
from shelf_scout.models import Fulfillment, StockState
from shelf_scout.pollers import ParseError, PollError, ebay

TEXT = (Path(__file__).parent / "fixtures" / "ebay" / "search.json").read_text()
MSRP = 89999


def test_parse_keeps_only_real_deals_and_reports_cheapest():
    good, cheapest = ebay.parse(TEXT, MSRP)
    assert [g.url[-1] for g in good] == ["1", "8"]
    assert good[0].price_cents == 84999 and good[0].fulfillment is Fulfillment.SHIP
    assert good[1].fulfillment is Fulfillment.PICKUP and "99.5" in good[0].seller
    assert cheapest == 80000   # the pickup listing; the 909.00 one is real but over MSRP


def test_parse_over_msrp_only_and_garbage():
    over = json.dumps({"itemSummaries": json.loads(TEXT)["itemSummaries"][1:2]})
    assert ebay.parse(over, MSRP) == ([], 90900)
    assert ebay.parse("{}", MSRP) == ([], None)   # eBay omits itemSummaries when nothing matches
    with pytest.raises(ParseError):
        ebay.parse('{"itemSummaries": [{"nope": 1}]}', MSRP)


def make(replies, api_key="id:secret"):
    queue, calls = list(replies), []

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 7200})
        return httpx.Response(200, text=queue.pop(0))

    s = config.validate({"retailers": {"ebay": {"enabled": True, "api_key": api_key}}})
    return ebay.Ebay(httpx.AsyncClient(transport=httpx.MockTransport(handler)), lambda: s), calls


def test_poll_closes_vanished_listings_and_summarises_when_empty():
    poller, calls = make([TEXT, "{}"])
    first = asyncio.run(poller.check())
    assert {r.state for r in first} == {StockState.IN_STOCK} and len(first) == 2
    assert calls[1].headers["authorization"] == "Bearer tok"
    second = asyncio.run(poller.check())   # both listings gone: each closes, plus one summary row
    assert sorted(r.state.value for r in second) == ["out_of_stock"] * 3
    assert "no real listings" in second[-1].detail
    assert sum(c.url.path.endswith("/token") for c in calls) == 1   # token reused


def test_missing_or_malformed_key_is_a_plain_error():
    for key in ("", "justoneword"):
        poller, _ = make([], api_key=key)
        with pytest.raises(PollError, match="api_key"):
            asyncio.run(poller.check())
