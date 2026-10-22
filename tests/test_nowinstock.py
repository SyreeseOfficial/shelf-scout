"""NowInStock poller. tests/fixtures/nowinstock.html is a real capture (table rows only) of the PS5 page."""
from pathlib import Path

import pytest

from shelf_scout.models import StockState
from shelf_scout.pollers import ParseError, PollError, nowinstock

TEXT = (Path(__file__).parent / "fixtures" / "nowinstock.html").read_text()


def test_only_pro_listings_and_all_are_out_of_stock_in_the_capture():
    got = nowinstock.parse(TEXT, ["Console: Pro"])
    assert len(got) == 8 and {r.state for r in got} == {StockState.OUT_OF_STOCK}
    assert all("Pro" in r.detail for r in got) and any("Amazon" in r.seller for r in got)


def test_in_stock_row_gets_price_store_and_link():
    (r,) = nowinstock.parse(TEXT, ["Digital Slim 825GB : Newegg"])
    assert r.state is StockState.IN_STOCK and r.price_cents == 59900
    assert r.seller.startswith("Newegg") and "unverified" in r.seller and "newegg.com" in r.url


def test_unknown_price_and_bad_page():
    (r,) = nowinstock.parse(TEXT, ["Digital Slim 825GB : Amazon"])   # "Too Low": Amazon hides the price
    assert r.state is StockState.IN_STOCK and r.price_cents is None
    with pytest.raises(ParseError):
        nowinstock.parse("<html>changed</html>", ["Console: Pro"])
    with pytest.raises(PollError):
        nowinstock.parse(TEXT, ["no such console"])
