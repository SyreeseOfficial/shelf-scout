"""Amazon: the product page (/dp/<ASIN>). Page layer only.

STATUS: as of this writing amazon.com answers an honest, non-browser client with a bot-check page
("Click the button below to continue shopping", HTTP 200), so live reads fail with a "blocked" error.
We don't get around that. Amazon's official route (Product Advertising API) needs an affiliate account
with qualifying sales, so it isn't an option here. The parser below works from Amazon's known product-page
markup but has NOT been checked against a live page; its in/out fixtures are hand-written. It is
deliberately strict: anything it doesn't recognise is a parse error, never "out of stock".

Put listings in settings.json as retailers.amazon.urls (full links) and/or retailers.amazon.skus (ASINs,
the 10-character code after /dp/ in the product URL).
How to re-find the selectors: open a product page, DevTools -> Elements, search for
id="add-to-cart-button", id="availability", id="merchant-info", class="a-offscreen".
"""
import re
import time

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from ..models import Fulfillment, Layer, Reading, StockState
from . import ParseError, Poller, to_cents


def _text(tree: HTMLParser, selector: str) -> str | None:
    node = tree.css_first(selector)
    return re.sub(r"\s+", " ", node.text()).strip() if node else None


def parse(html: str, url: str) -> list[Reading]:
    tree = HTMLParser(html)
    now = time.time()
    # Real product pages always carry the title; anything without it isn't a page we understand.
    name = _text(tree, "#productTitle")
    if not name:
        raise ParseError("no #productTitle on the page: it isn't an Amazon product page we recognise. "
                         "Check the link in settings.json, or Amazon changed its layout")
    can_buy = tree.css_first("#add-to-cart-button, #buy-now-button") is not None
    availability = (_text(tree, "#availability") or "").lower()
    if can_buy:
        price = _text(tree, "#corePrice_feature_div .a-offscreen, .a-price .a-offscreen")
        # "Ships from Amazon.com Sold by Amazon.com" vs a marketplace seller: shown as-is so the owner can judge.
        seller = _text(tree, "#merchant-info, #tabular-buybox .tabular-buybox-text[role=presentation]")
        return [Reading("amazon", StockState.IN_STOCK, Layer.PAGE, url, to_cents(price) if price else None,
                        seller, Fulfillment.SHIP, name, now)]
    if "currently unavailable" in availability:
        return [Reading("amazon", StockState.OUT_OF_STOCK, Layer.PAGE, url, None, None, None, name, now)]
    raise ParseError("product page has neither a buy button nor 'Currently unavailable': can't tell the stock state. "
                     "Amazon may have changed its layout")


class Amazon(Poller):
    retailer, layer = "amazon", Layer.PAGE

    async def check(self) -> list[Reading]:
        urls = list(self.cfg["urls"]) + [f"https://www.amazon.com/dp/{asin}" for asin in self.cfg["skus"]]

        async def one(url: str, _key: str) -> list[Reading]:
            return parse((await self.get(url)).text, url)

        return await self.each([(u, u) for u in urls], one,
                               "retailers.amazon has no urls or skus in settings.json: add the PS5 Pro link or ASIN")


POLLER = Amazon
