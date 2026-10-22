# TODO: open issues

Found while building Phase 3 (2026-10-22). Owner actions first, then code follow-ups.

## Owner actions

- [ ] **Best Buy API key.** Create a free key at https://developer.bestbuy.com/ and set `retailers.bestbuy.api_key` in `settings.json`. Until then Best Buy shows an error in `health`.
- [ ] **Best Buy SKU.** Find the PS5 Pro SKU (the number after `skuId=` in its product page URL) and set `retailers.bestbuy.skus`. I couldn't find the real one.
- [ ] **Amazon ASIN.** Find the PS5 Pro ASIN (the 10 characters after `/dp/`) and set `retailers.amazon.skus`. `B0DGY63Z2H` came from an old deal post and is unverified.

## Blocked sources (not bypassed on purpose)

- [ ] **Amazon is blocked.** amazon.com serves a bot-check page (HTTP 200) to an honest client, so `poll-once amazon` reports `blocked`. Rely on the tracker layer (Phase 5) and Amazon's own notify-me alerts. Re-test now and then; it may stop blocking.
- [ ] **bestbuy.com drops our connection.** Only the official API works. The Best Buy page layer is not available.

## Untested against live sites

- [ ] **Amazon parser** (`pollers/amazon.py`) uses hand-written in/out fixtures. Check it against a live in-stock and out-of-stock page if Amazon ever lets us read one.
- [ ] **Best Buy parser** (`pollers/bestbuy.py`) uses hand-written fixtures shaped like the API docs. Check it against a real API reply once the key is set (`python -m shelf_scout poll-once bestbuy`).
- [ ] **Sony in-stock case on the PS5 Pro itself.** The in-stock fixture is the real response for a different product (the disc drive), because the Pro is out of stock right now. Re-capture when the Pro is in stock.

## Gaps vs BUILD_PLAN.md

- [ ] **Phase 3 "10 minute run" check.** I ran the full service for about 3 minutes. Do a 10 minute run and look at the health panel.
- [ ] **Sony page layer skipped.** The page HTML has no stock state (JavaScript fills it in and "Add to Cart" is always present), so only the endpoint layer exists.
- [ ] **Phase 4 not started.** Walmart, Target, GameStop, Costco and local stock near ZIP 98036. Expect the same kind of blocks.
