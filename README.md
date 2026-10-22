# shelf-scout

Free, local PS5 Pro stock alerts. See `PRD.md` (what/why) and `BUILD_PLAN.md` (how/order).

## Quick start

**Install** (Python 3.11+, Linux):

```
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp settings.example.json settings.json   # optional: defaults work without it
```

**Configure.** Start it (below) and open http://127.0.0.1:8765/settings, or edit `settings.json`. The must-dos: your ntfy alert and ack topics (see "Phone alerts"), a free Best Buy API key + SKU, and any retailer links you want (GameStop, Costco, Amazon). The first lines of the log (`self-check`) say what is still missing.

**Start:**

```
.venv/bin/python -m shelf_scout     # Ctrl+C to stop
```

For unattended use, run it as a service instead (see "Run it as a service").

**Test:**

```
.venv/bin/python -m shelf_scout test            # a fake restock to every channel; repeats until you acknowledge
.venv/bin/python -m shelf_scout test --quiet    # a fake over-cap restock: one low-priority message
.venv/bin/python -m shelf_scout doctor          # pass/fail checklist of everything a real alert needs
.venv/bin/pytest                                # the code's own tests
```

**Update a product link** (a dead link shows as an error in Bot health): Settings -> Retailers, change the links/ids, Save. It applies at once.

**Stop:** Ctrl+C in the terminal, or `systemctl --user stop shelf-scout`. To pause alerts without stopping the program, use **Stop everything** on the dashboard.

## Dress rehearsal (do this once before the real drop)

1. `.venv/bin/python -m shelf_scout doctor` and read every FAIL line. Blocked retailers are expected to fail (see the retailer table); anything about your channels, ack topic or settings is not.
2. `.venv/bin/python -m shelf_scout test` (or the dashboard's **Test alert** button). Confirm: the phone push arrives and its link opens; the Discord/Telegram message arrives; the PC alarm plays; it repeats after `repeat_seconds`; tapping **Acknowledge** on the phone stops it within one interval.
3. Leave the service running for 24 hours, then open the dashboard's **Bot health** panel: every source should be OK or a known, explained block, and the log should have no repeated errors.

## Dashboard

With the service running, open **http://127.0.0.1:8765/**. It shows live stock per retailer, price vs MSRP, restock history, bot health, upcoming sale days and PlayStation news, and refreshes itself every 5 seconds. Buttons: **Acknowledge** (stops the repeats), **Test alert**, **Stop everything** / **Resume** (pauses all polling and repeats; a restart resumes).

**Settings** (`/settings`) edits every setting (prices in dollars, quiet-hours windows, retailers and their links, channels, feeds) and applies it immediately, with no restart. It writes `settings.json` for you. Secrets (API keys, topics, webhooks, passwords) show only their last 4 characters; leave a secret box blank to keep it. The one exception is the dashboard's own address (`dashboard.host` / `port`), which needs a restart. There is no login, so keep the host at `127.0.0.1`: if you change it, shelf-scout logs a loud warning. Pages refuse form posts that come from other websites.

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
.venv/bin/python -m shelf_scout poll-once sony     # also: bestbuy, amazon, walmart, target, gamestop, costco
```

Prints what the retailer says right now. No alerts, nothing saved. The full service (`python -m shelf_scout`) polls every enabled retailer
every `interval_seconds` (+/- 20%), and on a block or error waits 2x, 4x, 8x... up to 30 min, then goes back to normal after one good poll.
You get one phone message per block, not one per retry.

### Retailer status (what was actually found)

| Retailer | Data source | Local stock (98036, 10 mi) | Status |
| --- | --- | --- | --- |
| Sony (PlayStation Direct) | Sony's own product JSON endpoint (the one its page calls) | No (ships only) | Works live, no setup. Page layer skipped: its HTML has no stock state. |
| Best Buy | Official Products API (free key) | No (API call is online availability only) | bestbuy.com drops our connection, so the API is the only honest route. **Needs your key** and the SKU: get a key at developer.bestbuy.com, set `retailers.bestbuy.api_key` and `retailers.bestbuy.skus`. Parser tested on hand-written fixtures only. |
| Amazon | Product page (`/dp/<ASIN>`) | No | amazon.com serves a bot-check page to us, so it reports `blocked`. Not bypassed. Set `retailers.amazon.skus` (ASIN) anyway; it only helps if Amazon stops blocking. Parser tested on hand-written fixtures only. |
| Target | The JSON endpoints target.com's own page calls (`redsky.target.com`) | **Yes**: nearest 5 stores within `radius_miles` of `zip` (pickup / in-store, store name shown) | **Works live** (checked: Lynnwood, Everett, Woodinville, Northgate stores + shipping). Its bot check (PerimeterX) blocked us for a while after a burst of test requests, then cleared; if it returns, shelf-scout backs off and recovers by itself. TCIN `93620188` is set by default. In-stock case is tested on hand-written fixtures only. |
| Walmart | Product page, schema.org JSON-LD (`/ip/<item id>`) | No (page has no per-store data) | walmart.com redirects us to its `/blocked` page, so it reports `blocked`. Not bypassed. Default item id `11839818124` came from a web search and is unverified. Marketplace sellers are labelled from the page. |
| GameStop | Product page, schema.org JSON-LD | No | gamestop.com answers HTTP 403 (bot check), so it reports `blocked`. Not bypassed. Put the full product link in `retailers.gamestop.urls` (I couldn't find the real PS5 Pro link). |
| Costco | Product page, schema.org JSON-LD | No | Costco serves pages to us, but lists the console only in short-lived bundles and I found no live link. Put the full link in `retailers.costco.urls` when one appears. Parser tested on hand-written fixtures only. |

Where a retailer has no per-store data, shelf-scout uses the online listing (as in the table). "Blocked" retailers are covered by the tracker layer (Phase 5) and each retailer's own notify-me alerts.

## Tracker feeds and news (works even when retailers block us)

`settings.json` -> `feeds` lists free RSS/Atom feeds. Each gets its own poller, back-off and `health` row (named after the feed), so a dead feed shows as an error, never as "no stock".

| Role | What it does |
| --- | --- |
| `"alert"` (default) | A new item whose title mentions a PS5 Pro **and** a restock word (restock, in stock, available, live) sends a **loud** alert labelled `unverified (tracker)` with no price. The alert closes after 30 min so the next hit alerts again. Old items (over 30 min) are ignored, so a restart doesn't replay history. |
| `"news"` | PS5 items are saved to the `announcements` table for the dashboard. Set `announcement_heads_up: true` for a quiet message on each new one (off by default). |

Defaults: Reddit r/consoledeals and Slickdeals (alert), the PlayStation Blog (news). All three work without an account. Reddit sometimes answers 403/429 when it's busy; shelf-scout backs off and retries. `type` is `rss` only. Trackalacker has no feed and builds its page with JavaScript, so keep using its own email/text alerts (the owner checklist covers this).
The sale calendar (Black Friday, Cyber Monday, ...) is `shelf_scout/trackers/sale_calendar.json`: add next year's dates there.

## Run it as a service (restarts itself)

```
mkdir -p ~/.config/systemd/user && cp deploy/shelf-scout.service ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now shelf-scout
loginctl enable-linger "$USER"      # keeps it running after you log out and starts it at boot
```

The unit assumes the repo is at `~/Documents/Code/shelf-scout` with its `.venv`; edit the two paths in the file if not. It restarts the process 5 seconds after any exit (checked: killing it brings it back with a new PID in seconds).
Logs: `journalctl --user -u shelf-scout -f`, and `logs/shelf_scout.log` (rotating: 1 MB x 3 files, so about 4 MB at most). Stop it: `systemctl --user stop shelf-scout`.

## What it tells you about itself

- **Startup self-check** (top of the log): which channels are on, which retailers can actually poll, and warnings for anything that won't work (empty ntfy topic, missing Best Buy key, ...).
- **"can't poll" message** when a source has had no good poll for `no_poll_alert_minutes` (default 10; slow feeds get 3x their interval), **"BLIND"** if every source is down, and one **"recovered"** message afterwards. Grouped per check, never one per retry. If your internet is down these can only reach the PC popup until it comes back.
- A crash in one retailer's loop restarts only that loop.

## Troubleshooting

**1. No alerts arrive.** Run `.venv/bin/python -m shelf_scout test`. If the phone gets nothing: the log's `self-check` lines say if `alert_topic` is empty; make sure the ntfy app is subscribed to exactly that topic. If only the PC alarm works, check `channels.ntfy.server` and your internet (`curl -I https://ntfy.sh`). On Android, set the ntfy Urgent channel to override Do Not Disturb.

**2. Phone Acknowledge doesn't stop the repeats.** Needs `channels.ntfy.ack_topic` set (the self-check warns if not). The ack path is the service subscribing to that topic: `journalctl --user -u shelf-scout | grep -i ack` shows if the listener is connected. The dashboard's **Acknowledge** button always works.

**3. A retailer shows Error or Blocked.** Dashboard -> Bot health shows the reason. "empty in settings.json" = add its link/id/key in Settings. "blocked" = the retailer's bot check; shelf-scout backs off and does not try to get around it, so lean on the tracker feeds and the retailer's own notify-me alerts. "not a PS5 Pro" or "sku not in reply" = a wrong or dead link: fix it in Settings. Test one retailer directly: `.venv/bin/python -m shelf_scout poll-once target`.

**4. The service won't start.** `systemctl --user status shelf-scout` and `journalctl --user -u shelf-scout -n 50`. A bad `settings.json` stops it with a message naming the setting; check by running `.venv/bin/python -m shelf_scout` in a terminal. If the unit says "No such file", the paths in the unit file are wrong.

**5. The dashboard won't open.** It is at http://127.0.0.1:8765/ (or your `dashboard.port`). `curl -I http://127.0.0.1:8765/` and `ss -ltnp | grep 8765`. If the log says "dashboard could not start", something else uses the port: change `dashboard.port` in `settings.json` and restart. Alerts keep working without the dashboard.

