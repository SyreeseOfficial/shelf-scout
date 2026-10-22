"""Shared reader for retailer product pages that publish schema.org JSON-LD (Walmart, GameStop, Costco).

Product pages put a machine-readable <script type="application/ld+json"> Product block in the HTML for
search engines, with offers.availability ("InStock" / "OutOfStock"), price and seller. That is steadier than
scraping page markup. Strict on purpose: no Product block, a different product, or an availability value we
don't know is a ParseError, never "out of stock".

Caveat: this is the page layer, so a CDN-cached page can lag the real stock by a minute or so.
"""
import json
import re
import time

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from ..models import Fulfillment, Layer, Reading, StockState
from . import ParseError, Poller, to_cents

# Guards against a link that quietly redirects to some other product (GameStop does this for unknown ids).
PS5_PRO = re.compile(r"(playstation\s*5|ps5)\s*pro", re.I)
IN = {"instock", "limitedavailability", "onlineonly", "instoreonly"}
OUT = {"outofstock", "soldout", "discontinued"}


def _product(html: str) -> dict | None:
    for node in HTMLParser(html).css('script[type="application/ld+json"]'):
        try:
            data = json.loads(node.text())
        except ValueError:
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for item in items:
            if isinstance(item, dict) and "Product" in (item.get("@type") if isinstance(item.get("@type"), list) else [item.get("@type")]):
                return item
    return None


def parse(html: str, retailer: str, label: str, url: str) -> list[Reading]:
    p = _product(html)
    if p is None:
        raise ParseError(f"no schema.org Product data on the {label} page: it isn't a product page we recognise "
                         "(wrong link, or the site changed). Check the link in settings.json")
    name = re.sub(r"[®™]", "", str(p.get("name", "")))
    if not PS5_PRO.search(name):
        raise ParseError(f"the {label} link is for {name!r}, not a PS5 Pro. Fix the link in settings.json")
    offers = p.get("offers")
    offers = offers if isinstance(offers, list) else [offers] if isinstance(offers, dict) else []
    kinds = [str(o.get("availability", "")).rsplit("/", 1)[-1].lower() for o in offers]
    buyable = [o for o, k in zip(offers, kinds) if k in IN]
    if buyable:
        o = buyable[0]
        k = kinds[offers.index(o)]
        price = o.get("price", o.get("lowPrice"))
        seller = o.get("seller")
        seller = seller.get("name") if isinstance(seller, dict) else seller
        return [Reading(retailer, StockState.IN_STOCK, Layer.PAGE, url, to_cents(price) if price not in (None, "") else None,
                        seller or label, Fulfillment.STORE if k == "instoreonly" else Fulfillment.SHIP, name, time.time())]
    if offers and all(k in OUT for k in kinds):
        return [Reading(retailer, StockState.OUT_OF_STOCK, Layer.PAGE, url, None, None, None, name, time.time())]
    raise ParseError(f"the {label} page's availability {kinds or 'missing'} isn't one we recognise, so the stock state is unknown. "
                     "The site may have changed its markup")


class JsonLdPoller(Poller):
    """Subclasses set retailer, label, and (if item ids map to a link) link_template with {sku}."""
    layer = Layer.PAGE
    label: str
    link_template: str | None = None

    async def check(self) -> list[Reading]:
        urls = list(self.cfg["urls"])
        if self.link_template:
            urls += [self.link_template.format(sku=s) for s in self.cfg["skus"]]

        async def one(url: str, _key: str) -> list[Reading]:
            return parse((await self.get(url)).text, self.retailer, self.label, url)

        return await self.each([(u, u) for u in urls], one,
                               f"retailers.{self.retailer}.urls is empty in settings.json: add the PS5 Pro product link"
                               + (f" (or its item id in skus)" if self.link_template else ""))
