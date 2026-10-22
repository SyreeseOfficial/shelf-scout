"""eBay: the official Browse API. Alerts on Buy It Now PS5 Pro listings at or under MSRP (price + shipping).

Needs a free developer keyset (https://developer.ebay.com/ -> Application Keys, Production). Put it in
settings.json as retailers.ebay.api_key, written "CLIENT_ID:CLIENT_SECRET" (the App ID and Cert ID).
retailers.ebay.skus holds the search words (default "PS5 Pro"), one search per entry.

Resale is full of accessories, empty boxes and scams, so a listing only counts if it passes every filter:
a title that says PS5 Pro, no junk words, a price over half of MSRP (a lone controller is not a console),
and a seller with real feedback. When nothing passes, the dashboard row says what the cheapest one was.

ponytail: the filters are constants, not settings. Hand-written fixtures (no key yet to capture a real reply).
"""
import base64
import json
import re
import time
from urllib.parse import quote_plus

from ..models import Fulfillment, Layer, Reading, StockState
from ..trackers.feeds import PS5_PRO
from . import ParseError, PollError, Poller, to_cents

TOKEN = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH = "https://api.ebay.com/buy/browse/v1/item_summary/search"
VIDEO_GAME_CONSOLES = "139971"
CONDITIONS = "1000|1500|3000"   # new, new other (open box), used
JUNK = re.compile(r"for parts|parts only|not working|broken|repair|empty box|box only|faceplate|decal|\bskin\b|read desc|no console", re.I)
MIN_FEEDBACK_PCT, MIN_FEEDBACK_SCORE = 95.0, 10
FLOOR = 0.5   # of MSRP


def parse(text: str, msrp_cents: int) -> tuple[list[Reading], int | None]:
    """(listings at/under MSRP that pass the filters, the cheapest passing price even if over MSRP)."""
    try:
        items = json.loads(text).get("itemSummaries", [])
        good, cheapest, now = [], None, time.time()
        for it in items:
            seller, title = it.get("seller", {}), it["title"]
            if not PS5_PRO.search(title) or JUNK.search(title):
                continue
            opts = it.get("shippingOptions") or []
            total = to_cents(it["price"]["value"]) + (to_cents(opts[0]["shippingCost"]["value"]) if opts and "shippingCost" in opts[0] else 0)
            pct, score = float(seller.get("feedbackPercentage", 0)), int(seller.get("feedbackScore", 0))
            if total < msrp_cents * FLOOR or pct < MIN_FEEDBACK_PCT or score < MIN_FEEDBACK_SCORE:
                continue
            cheapest = total if cheapest is None else min(cheapest, total)
            if total <= msrp_cents:
                good.append(Reading("ebay", StockState.IN_STOCK, Layer.ENDPOINT, it["itemWebUrl"], total,
                                    f"eBay: {seller.get('username', '?')} ({pct:g}%)",
                                    Fulfillment.SHIP if opts else Fulfillment.PICKUP,
                                    f"{it.get('condition', '')}: {title}"[:140], now))
        return good, cheapest
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ParseError("eBay's reply wasn't the shape we expect (item list with title, price, itemWebUrl). "
                         "eBay may have changed the API.") from None


class Ebay(Poller):
    retailer, layer = "ebay", Layer.ENDPOINT

    def __init__(self, *a):
        super().__init__(*a)
        self.token, self.token_until = "", 0.0
        self.live: set[str] = set()   # listing links reported in stock last poll; gone from results = sold or ended

    async def auth(self) -> str:
        if self.token and time.time() < self.token_until:
            return self.token
        key = self.cfg["api_key"]
        if ":" not in key:
            raise PollError('retailers.ebay.api_key in settings.json must look like "CLIENT_ID:CLIENT_SECRET": '
                            "get a free keyset at https://developer.ebay.com/")
        cid, secret = key.split(":", 1)
        r = await self.client.post(TOKEN, headers={"Authorization": "Basic " + base64.b64encode(f"{cid}:{secret}".encode()).decode()},
                                   data={"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"})
        if r.status_code != 200:
            raise PollError(f"eBay rejected the API key (HTTP {r.status_code}). Check retailers.ebay.api_key: use the Production App ID and Cert ID")
        body = r.json()
        self.token, self.token_until = body["access_token"], time.time() + body.get("expires_in", 7200) - 300
        return self.token

    async def check(self) -> list[Reading]:
        queries = self.cfg["skus"]
        if not queries:
            raise PollError("retailers.ebay.skus is empty in settings.json: add the search words, e.g. PS5 Pro")
        if not self.cfg["api_key"]:
            raise PollError("retailers.ebay.api_key is empty in settings.json: get a free keyset at https://developer.ebay.com/")
        msrp = self.get_settings()["msrp_cents"]
        headers = {"Authorization": f"Bearer {await self.auth()}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"}
        found: dict[str, Reading] = {}
        cheapest = None
        for q in queries:
            r = await self.get(SEARCH, headers=headers, params={
                "q": q, "category_ids": VIDEO_GAME_CONSOLES, "sort": "price", "limit": "50",
                "filter": f"buyingOptions:{{FIXED_PRICE}},conditionIds:{{{CONDITIONS}}},deliveryCountry:US,"
                          f"price:[{msrp * FLOOR / 100:.0f}..],priceCurrency:USD"})
            good, low = parse(r.text, msrp)
            found.update((g.url, g) for g in good)
            cheapest = low if cheapest is None or (low is not None and low < cheapest) else cheapest
        now = time.time()
        out = list(found.values())
        out += [Reading("ebay", StockState.OUT_OF_STOCK, Layer.ENDPOINT, u, None, None, None, None, now) for u in self.live - found.keys()]
        self.live = set(found)
        if not found:
            note = f"none at or under ${msrp / 100:,.0f}" + (f"; cheapest real listing ${cheapest / 100:,.0f}" if cheapest else "; no real listings found")
            out.append(Reading("ebay", StockState.OUT_OF_STOCK, Layer.ENDPOINT,
                               "https://www.ebay.com/sch/i.html?_nkw=" + quote_plus(queries[0]) + "&LH_BIN=1&_sop=15", None, None, None, note, now))
        return out


POLLER = Ebay
