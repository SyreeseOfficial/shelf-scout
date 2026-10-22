"""NowInStock.net: a free stock tracker we read instead of the retailers that block us.

Its PS5 page lists every console listing (Amazon, Walmart, Best Buy, Newegg, Sam's Club, ...) with In/Out of
Stock and a price, and its robots.txt allows reading that page. One gentle request per poll covers all of
them, so a blocked retailer still gets a signal. Third-party data, so a hit is labelled unverified and the
link is theirs (a retailer link carrying their affiliate tag; that is how the site pays for itself).

retailers.nowinstock.urls = the page (default: the PS5 page); retailers.nowinstock.skus = text a listing's
name must contain (default "Console: Pro", which matches every PS5 Pro listing).

ponytail: regex over the table rows, no HTML parser dependency. If the page layout changes, check() raises
ParseError ("no listing rows") instead of reporting everything sold out.
"""
import html
import re
import time

from ..models import Fulfillment, Layer, Reading, StockState
from . import ParseError, PollError, Poller, to_cents

PAGE = "https://www.nowinstock.net/videogaming/consoles/sonyps5/"
ROW = re.compile(r'<tr id="tr\d+".*?</tr>', re.S)
LINK = re.compile(r'<a href="([^"]+)"[^>]*>([^<]+)</a>')
STATUS = re.compile(r'class="stockStatus(\w+)"')
PRICE = re.compile(r'class="trackerPrice[^"]*">([^<]*)<')


def parse(text: str, wanted: list[str], page: str = PAGE) -> list[Reading]:
    """One Reading per listing whose name contains a `wanted` phrase. Only status "In" counts as in stock."""
    rows = ROW.findall(text)
    if not rows:
        raise ParseError("no listing rows on the NowInStock page: the layout may have changed, or the URL is wrong")
    out, now = [], time.time()
    for row in rows:
        link, status, price = LINK.search(row), STATUS.search(row), PRICE.search(row)
        if not (link and status):
            continue
        name = html.unescape(link.group(2)).strip()   # "Console: Pro 2TB (CFI-7119) : Amazon"
        if not any(w.lower() in name.lower() for w in wanted):
            continue
        product, _, store = name.rpartition(" : ")
        try:
            cents = to_cents(price.group(1)) if price and "$" in price.group(1) else None   # "-", "See Site", "Too Low" -> unknown
        except ParseError:
            cents = None
        state = StockState.IN_STOCK if status.group(1) == "In" else StockState.OUT_OF_STOCK
        out.append(Reading("nowinstock", state, Layer.TRACKER, html.unescape(link.group(1)), cents if state is StockState.IN_STOCK else None,
                           f"{store or '?'} (unverified, via NowInStock)", Fulfillment.SHIP, product or name, now))
    if not out:
        raise PollError(f"no NowInStock listing matches {wanted}. Change retailers.nowinstock.skus in settings.json")
    return out


class NowInStock(Poller):
    retailer, layer = "nowinstock", Layer.TRACKER

    async def check(self) -> list[Reading]:
        return parse((await self.get((self.cfg["urls"] or [PAGE])[0])).text, self.cfg["skus"])


POLLER = NowInStock
