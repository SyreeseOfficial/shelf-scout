"""PlayStation Direct: Sony's own product-list JSON endpoint (the one its product page calls).

How to re-find this if it breaks: open the product page in a browser, DevTools -> Network, filter
"productList". The product code (SKU) is also in the page HTML as data-product-code="1000050928".

Only the endpoint layer: the product page itself has no stock state in its HTML (the stock is filled
in by JavaScript, and the page always contains an "Add to Cart" button), so reading the page
would give false "in stock" answers.
"""
import json
import time

from ..models import Fulfillment, Layer, Reading, StockState
from . import ParseError, Poller, to_cents

API = "https://api.direct.playstation.com/commercewebservices/ps-direct-us/users/anonymous/products/productList"
FALLBACK_URL = "https://direct.playstation.com/en-us/consoles"
# stockLevelStatus values: inStock / lowStock count as buyable. Anything we haven't seen (e.g. a "coming soon"
# status) becomes an ERROR, never "out of stock".
IN_STOCK = {"instock", "lowstock"}


def parse(text: str, listings: dict[str, str]) -> list[Reading]:
    """`listings` maps sku -> link. One Reading per sku asked for; a sku missing from the reply is an error."""
    try:
        products = {p["code"]: p for p in json.loads(text)["products"]}
    except (ValueError, KeyError, TypeError):
        raise ParseError("Sony's product API reply wasn't in the expected shape (no 'products' list). "
                         "Sony may have changed it: see the note at the top of pollers/sony.py") from None
    now, out = time.time(), []
    for sku, url in listings.items():
        p = products.get(sku)
        if p is None:
            out.append(Reading("sony", StockState.ERROR, Layer.ENDPOINT, url, None, None, None,
                               f"sku {sku} not in Sony's reply: check it in settings.json (retailers.sony.skus)", now))
            continue
        status = str(p.get("stock", {}).get("stockLevelStatus", ""))
        if status.lower() in IN_STOCK:
            state = StockState.IN_STOCK
        elif status.lower() == "outofstock":
            state = StockState.OUT_OF_STOCK
        else:
            out.append(Reading("sony", StockState.ERROR, Layer.ENDPOINT, url, None, None, None,
                               f"sku {sku}: unrecognised stock status {status!r}", now))
            continue
        value = p.get("price", {}).get("value")
        out.append(Reading("sony", state, Layer.ENDPOINT, url, to_cents(value) if value is not None else None,
                           "PlayStation Direct (Sony)", Fulfillment.SHIP, p.get("name"), now))
    return out


class Sony(Poller):
    retailer, layer = "sony", Layer.ENDPOINT

    async def check(self) -> list[Reading]:
        skus, urls = self.cfg["skus"], self.cfg["urls"]
        if not skus:
            raise ParseError("retailers.sony.skus is empty in settings.json: add the product code (e.g. 1000050928)")
        listings = {sku: urls[i] if i < len(urls) else FALLBACK_URL for i, sku in enumerate(skus)}
        r = await self.get(API, params={"fields": "BASIC", "productCodes": ",".join(skus)})
        return parse(r.text, listings)


POLLER = Sony
