"""Data shapes shared by pollers, trackers, the engine and notifiers."""
from dataclasses import dataclass
from enum import Enum


class StockState(str, Enum):
    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"
    ERROR = "error"  # parse error, block, network failure. NEVER treat as out of stock.


class Layer(str, Enum):
    PAGE = "page"
    ENDPOINT = "endpoint"
    TRACKER = "tracker"


class Fulfillment(str, Enum):
    SHIP = "ship"
    PICKUP = "pickup"
    STORE = "store"  # in-store, includes store name in `detail`


@dataclass
class Reading:
    """What every poller/tracker returns, one per listing checked."""
    retailer: str  # "bestbuy", "sony", ...
    state: StockState
    layer: Layer
    url: str  # direct listing link, tap-to-buy
    price_cents: int | None
    seller: str | None  # "Sold by retailer" or marketplace seller name
    fulfillment: Fulfillment | None
    detail: str | None  # store name, SKU/bundle name, or error text
    at: float  # unix timestamp


@dataclass
class Alert:
    event_id: int
    loud: bool
    rows: list[Reading]  # sorted by price, then detection time
    test: bool = False
    msrp_cents: int = 89999  # lets notifiers print "+$150" without needing settings
