"""Best Buy: the official Products API (api.bestbuy.com). Needs a free API key.

Why not the website: bestbuy.com drops connections from an honest, non-browser client (even the home
page), and we don't disguise ourselves. The developer API is the sanctioned way to read availability.
Get a key (free, needs a Best Buy account) at https://developer.bestbuy.com/ and put it in
settings.json as retailers.bestbuy.api_key. Put the product SKUs in retailers.bestbuy.skus: it's the
number after skuId= in the product page URL.

Only the endpoint layer: the product page is what the site blocks.
"""
import json
import time

from ..models import Fulfillment, Layer, Reading, StockState
from . import ParseError, PollError, Poller, to_cents

API = "https://api.bestbuy.com/v1/products/{sku}.json"
SHOW = "sku,name,salePrice,onlineAvailability,url"


def parse(text: str, sku: str, link: str) -> list[Reading]:
    try:
        p = json.loads(text)
        online = p["onlineAvailability"]
        if not isinstance(online, bool):
            raise TypeError
    except (ValueError, KeyError, TypeError):
        raise ParseError(f"Best Buy API reply for sku {sku} had no true/false onlineAvailability. "
                         "Check the SKU in settings.json, or Best Buy may have changed the API.") from None
    price = p.get("salePrice")
    return [Reading("bestbuy", StockState.IN_STOCK if online else StockState.OUT_OF_STOCK, Layer.ENDPOINT, link,
                    to_cents(price) if price is not None else None, "Best Buy", Fulfillment.SHIP, p.get("name"), time.time())]


class BestBuy(Poller):
    retailer, layer = "bestbuy", Layer.ENDPOINT

    async def check(self) -> list[Reading]:
        key, skus, urls = self.cfg["api_key"], self.cfg["skus"], self.cfg["urls"]
        if not key:
            raise PollError("retailers.bestbuy.api_key is empty in settings.json: get a free key at https://developer.bestbuy.com/")
        items = [(urls[i] if i < len(urls) else f"https://www.bestbuy.com/site/{sku}.p?skuId={sku}", sku)
                 for i, sku in enumerate(skus)]

        async def one(link: str, sku: str) -> list[Reading]:
            r = await self.get(API.format(sku=sku), params={"apiKey": key, "format": "json", "show": SHOW})
            return parse(r.text, sku, link)

        return await self.each(items, one, "retailers.bestbuy.skus is empty in settings.json: add the PS5 Pro SKU")


POLLER = BestBuy
