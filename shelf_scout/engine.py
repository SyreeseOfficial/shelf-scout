"""Alert engine. Phase 1 only has the test-data helper; dedupe/tiers/ack arrive in Phase 2."""
import time

from .models import Fulfillment, Layer, Reading, StockState


def fake_reading(retailer="fakemart", price_cents=89999, **overrides) -> Reading:
    """A believable in-stock Reading for test mode."""
    fields = dict(
        retailer=retailer, state=StockState.IN_STOCK, layer=Layer.PAGE,
        url=f"https://example.com/{retailer}/ps5-pro", price_cents=price_cents,
        seller="Sold by retailer", fulfillment=Fulfillment.SHIP,
        detail="TEST PS5 Pro", at=time.time(),
    )
    fields.update(overrides)
    return Reading(**fields)
