"""Target: the JSON endpoints target.com's own pages call (redsky.target.com). Endpoint layer only.

Gives online shipping stock AND per-store stock near settings `zip` / `radius_miles`, so this is the
retailer that supports local stock. Put the product's TCIN (the number after A- in the product URL,
e.g. .../A-93620188) in retailers.target.skus.

How to re-find this if it breaks: open the product page, DevTools -> Network, filter "redsky".
`product_fulfillment_v1` is the stock call, `nearby_stores_v1` the store list, `pdp_client_v1` the price.
KEY below is the public web key Target's own site sends with every call (it is not a secret and not ours).

Cost: one store-list call an hour, then one stock call per nearby store per poll (capped at MAX_STORES),
plus one price call only when something is actually in stock.
"""
import json
import time
from dataclasses import replace

from ..models import Fulfillment, Layer, Reading, StockState
from . import ParseError, PollError, Poller, to_cents

KEY = "9f36aeafbe60771e321a7cc95a78140772ab3e96"
BASE = "https://redsky.target.com/redsky_aggregations/v1/web"
MAX_STORES = 3      # ponytail: nearest 3 only (5 got us flagged for hours), to keep requests per poll low; raise if you want a wider net
STORE_REFRESH = 3600
IN = {"IN_STOCK", "LIMITED_STOCK"}
# UNAVAILABLE = Target doesn't offer that route for this item. Anything else we haven't seen is an error, not "out".
OUT = {"OUT_OF_STOCK", "UNAVAILABLE", "NOT_SOLD_IN_STORE"}


def _state(status, what: str) -> StockState:
    if status in IN:
        return StockState.IN_STOCK
    if status in OUT:
        return StockState.OUT_OF_STOCK
    raise ParseError(f"Target gave an unrecognised {what} status {status!r}. Target may have changed its API: see the note at the top of pollers/target.py")


def parse_stores(text: str) -> list[str]:
    try:
        stores = json.loads(text)["data"]["nearby_stores"]["stores"]
        return [str(s["store_id"]) for s in stores][:MAX_STORES]
    except (ValueError, KeyError, TypeError):
        raise ParseError("Target's store-list reply wasn't in the expected shape (no data.nearby_stores.stores). "
                         "Check zip in settings.json, or see the note at the top of pollers/target.py") from None


def parse_fulfillment(text: str, tcin: str, link: str) -> list[Reading]:
    """One shipping reading plus one reading per store in the reply. Store readings get '#store-<id>' on the
    link so the engine treats each store as its own listing (it dedupes on retailer + link)."""
    try:
        f = json.loads(text)["data"]["product"]["fulfillment"]
        ship = _state(f["shipping_options"]["availability_status"], "shipping")
        stores = f["store_options"]
    except (ValueError, KeyError, TypeError):
        raise ParseError(f"Target's stock reply for TCIN {tcin} wasn't in the expected shape. "
                         "Check the TCIN in settings.json (retailers.target.skus), or see the note at the top of pollers/target.py") from None
    now = time.time()
    out = [Reading("target", ship, Layer.ENDPOINT, link, None, "Target", Fulfillment.SHIP, None, now)]
    for s in stores:
        pickup = _state(s["order_pickup"]["availability_status"], "pickup")
        in_store = _state(s["in_store_only"]["availability_status"], "in-store")
        state = StockState.IN_STOCK if StockState.IN_STOCK in (pickup, in_store) else StockState.OUT_OF_STOCK
        how = Fulfillment.PICKUP if pickup is StockState.IN_STOCK else Fulfillment.STORE
        name = s["store"]["location_name"]
        out.append(Reading("target", state, Layer.ENDPOINT, f"{link}#store-{s['location_id']}", None, "Target", how, f"{name} store", now))
    return out


def parse_price(text: str) -> int | None:
    try:
        return to_cents(json.loads(text)["data"]["product"]["price"]["current_retail"])
    except (ValueError, KeyError, TypeError, ParseError):
        return None  # price is a nice-to-have: an in-stock alert with "price unknown" still goes out (loud)


class Target(Poller):
    retailer, layer = "target", Layer.ENDPOINT
    burst_ok = False  # PerimeterX blocked us once after a few quick requests (see TODO.md)

    def __init__(self, *a):
        super().__init__(*a)
        self.stores: list[str] = []
        self.stores_at = 0.0
        self.zip_key = None  # (zip, radius) the cached store list was fetched for

    async def nearby_stores(self) -> list[str]:
        s = self.get_settings()
        if not self.stores or time.time() - self.stores_at > STORE_REFRESH or self.zip_key != (s["zip"], s["radius_miles"]):
            r = await self.get(f"{BASE}/nearby_stores_v1", params={"key": KEY, "place": s["zip"], "limit": MAX_STORES,
                                                                   "within": s["radius_miles"], "channel": "WEB"})
            self.stores, self.stores_at, self.zip_key = parse_stores(r.text), time.time(), (s["zip"], s["radius_miles"])
            if not self.stores:
                raise PollError(f"Target lists no stores within {s['radius_miles']} miles of {s['zip']}: check zip/radius_miles in settings.json")
        return self.stores

    async def check(self) -> list[Reading]:
        skus, urls = self.cfg["skus"], self.cfg["urls"]
        stores = await self.nearby_stores()
        zip_code = self.get_settings()["zip"]
        items = [(urls[i] if i < len(urls) else f"https://www.target.com/p/-/A-{t}", t) for i, t in enumerate(skus)]

        async def one(link: str, tcin: str) -> list[Reading]:
            seen: dict[str, Reading] = {}
            for store in stores:
                r = await self.get(f"{BASE}/product_fulfillment_v1", params={
                    "key": KEY, "tcin": tcin, "store_id": store, "zip": zip_code, "required_store_id": store,
                    "has_required_store_id": "true", "channel": "WEB"})
                for rd in parse_fulfillment(r.text, tcin, link):
                    seen.setdefault(rd.url, rd)  # the shipping reading repeats in every reply; keep the first
            readings = list(seen.values())
            if any(r.state is StockState.IN_STOCK for r in readings):
                price = None
                try:
                    price = parse_price((await self.get(f"{BASE}/pdp_client_v1", params={"key": KEY, "tcin": tcin, "channel": "WEB"})).text)
                except PollError:
                    pass
                readings = [r if r.state is not StockState.IN_STOCK else replace(r, price_cents=price) for r in readings]
            return readings

        return await self.each(items, one, "retailers.target.skus is empty in settings.json: add the PS5 Pro TCIN (e.g. 93620188)")


POLLER = Target
