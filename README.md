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

(Full setup, troubleshooting and the retailer table arrive in later phases.)
