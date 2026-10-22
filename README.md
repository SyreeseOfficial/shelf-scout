# shelf-scout

Free, local PS5 Pro stock alerts. See `PRD.md` (what/why) and `BUILD_PLAN.md` (how/order).

## Setup

```
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp settings.example.json settings.json   # optional: defaults work without it
```

## Run

```
.venv/bin/python -m shelf_scout     # Ctrl+C to stop
.venv/bin/pytest
```

## Phone alerts (ntfy)

1. Install the ntfy app. Subscribe to a long random alert topic (e.g. `ps5-alert-x7k2q9m4w8`).
2. Pick a second random topic for acks (e.g. `ps5-ack-r3t8v1n6z5`). The app doesn't need to subscribe to it.
3. Put both in `settings.json` under `channels.ntfy` (`alert_topic`, `ack_topic`). Anyone who knows a topic name can read or publish to it, so keep them secret.
4. **Android:** in ntfy, open the topic's notification settings and turn on "Override Do Not Disturb" for the Urgent channel, or loud alerts will be silenced at night.
5. `.venv/bin/python -m shelf_scout test` sends a fake loud restock to every enabled channel (phone, Discord/Telegram, PC alarm). It repeats every `repeat_seconds` until you tap **Acknowledge** on the phone.
   `... test --quiet` sends a fake over-cap restock: one low-priority message, no repeat.

Over-cap (quiet) alerts skip the SMS channel and the PC alarm sound.

## Checking a retailer

```
.venv/bin/python -m shelf_scout poll-once sony     # also: bestbuy, amazon
```

Prints what the retailer says right now. No alerts, nothing saved. The full service (`python -m shelf_scout`) polls every enabled retailer
every `interval_seconds` (+/- 20%), and on a block or error waits 2x, 4x, 8x... up to 30 min, then goes back to normal after one good poll.
You get one phone message per block, not one per retry.

### Retailer status (what was actually found)

| Retailer | Data source | Status |
| --- | --- | --- |
| Sony (PlayStation Direct) | Sony's own product JSON endpoint (the one its page calls) | Works live, no setup. Page layer skipped: its HTML has no stock state. |
| Best Buy | Official Products API (free key) | bestbuy.com drops our connection, so the API is the only honest route. **Needs your key** and the SKU: get a key at developer.bestbuy.com, set `retailers.bestbuy.api_key` and `retailers.bestbuy.skus`. Parser tested on hand-written fixtures only. |
| Amazon | Product page (`/dp/<ASIN>`) | amazon.com serves a bot-check page to us, so it reports `blocked`. Not bypassed. Set `retailers.amazon.skus` (ASIN) anyway; it only helps if Amazon stops blocking. Parser tested on hand-written fixtures only. |

(Full setup, troubleshooting and the rest of the retailer table arrive in later phases.)
