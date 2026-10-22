# BUILD_PLAN.md: PS5 Pro Stock Alert Tool (shelf-scout)

Source of truth for *what* and *why*: `PRD.md`. This file is the *how* and *in what order*.
If this file and `PRD.md` disagree, `PRD.md` wins. Flag the conflict to the owner.

---

## 0. Instructions for the AI building this

Read this whole file first. Then build **one phase at a time, in order**.

**Working loop (every phase):**
1. Re-read the phase section and the contracts in section 3.
2. Write the code for that phase only.
3. Run the phase's **Done when** checks. Show the output.
4. Stop. Tell the owner what now works and the exact command to try it. Wait for "next".

**Hard rules:**
- Simple beats clever. Fewest files, fewest dependencies, stdlib first.
- Comment the *why* in plain English. The owner wants to debug this as little as possible.
- Every error message must say what failed, where, and what to try. No bare stack traces in the UI or alerts.
- A parser that cannot read a page must raise a **parse error**. It must NEVER return "out of stock" on failure.
- Never store retailer credentials or payment data. Never automate login, cart or checkout.
- No proxies, no user-agent spoofing, no CAPTCHA solving. On a block: back off and report.
- Everything free. No paid APIs, no paid services.
- Do not add features not listed here. Park ideas in `## Parked` at the bottom of this file.

**Not your job:** Phase 0 (owner's accounts, phone setup, companion trackers). See section 9.

---

## 1. Fixed decisions (do not re-debate)

| Topic | Decision |
| --- | --- |
| Language | Python 3.11+, Linux |
| Concurrency | One process, `asyncio`. One task per retailer poller. |
| HTTP | `httpx` (async) |
| HTML parsing | `selectolax` or `beautifulsoup4` (pick one, use it everywhere) |
| Dashboard | `FastAPI` + `uvicorn`, server-rendered HTML with Jinja2 + a little vanilla JS. No build step, no JS framework. |
| Storage | `settings.json` (config + secrets) and `shelf_scout.db` (SQLite via stdlib `sqlite3`: history, health, events) |
| Notifications | ntfy (primary), Discord webhook or Telegram bot, email-to-SMS (best effort), local PC alarm |
| Ack path | ntfy action button publishes to a private ack topic; the bot subscribes (outbound only, no open ports) |
| Service | systemd **user** service, auto-restart |
| Tests | `pytest`, small. One test file per tricky module. No mocks of the whole world. |
| Money | Store prices as `float` dollars rounded to 2 places, or integer cents. Pick cents and stay consistent. |

**Product rules (from PRD):**
- Any new PS5 Pro SKU counts (console or MSRP bundle). New condition only.
- MSRP `89999` cents. Tolerance default `5000` cents. Cap default `94999` cents. All editable.
- At or under cap = **loud** (all channels, repeat every 60 s until acked). Over cap = **quiet** (one low-priority message, no repeat).
- Alert on every seller. Label the seller. Do not filter marketplace sellers.
- No verification delay. Alert on the first signal from any layer.
- Poll each retailer every 30-60 s with small random jitter. Per-retailer interval editable.
- Multiple retailers in stock at once: one combined alert, ranked by price then detection speed, link for each.
- Ack stops repeats for that restock event. A new out-of-stock to in-stock transition starts a new event.
- Local stock: in-store within 10 miles of Lynnwood, WA (ZIP 98036) where the retailer exposes it. Otherwise fall back to online listing.

---

## 2. Repo layout (target)

```
shelf-scout/
  PRD.md
  BUILD_PLAN.md
  pyproject.toml            # deps + entry point
  settings.example.json     # committed template, no secrets
  settings.json             # real config, gitignored
  .gitignore                # settings.json, *.db, logs/
  shelf_scout/
    __main__.py             # `python -m shelf_scout` starts everything
    models.py               # dataclasses from section 3
    config.py               # load/save/validate settings.json
    db.py                   # sqlite helpers
    engine.py               # alert engine: dedupe, tiers, quiet hours, repeat loop, ack
    notifiers/
      __init__.py           # Notifier protocol + fan-out
      ntfy.py
      chat.py               # discord + telegram
      sms.py                # email-to-SMS
      pc.py                 # local sound + popup
    pollers/
      __init__.py           # Poller base class, backoff, health, registry
      sony.py  bestbuy.py  amazon.py  walmart.py  target.py  gamestop.py  costco.py
    trackers/
      feeds.py              # third-party trackers / RSS
      events.py             # sale calendar + announcements
    web/
      app.py                # FastAPI routes
      templates/            # dashboard.html, settings.html
      static/
  tests/
  deploy/
    shelf-scout.service     # systemd user unit
  README.md                 # setup + run + troubleshoot (plain English)
```

---

## 3. Contracts (build against these exactly)

```python
# models.py
from dataclasses import dataclass
from enum import Enum

class StockState(str, Enum):
    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"
    ERROR = "error"            # parse error, block, network failure. NEVER treat as out of stock.

class Layer(str, Enum):
    PAGE = "page"
    ENDPOINT = "endpoint"
    TRACKER = "tracker"

class Fulfillment(str, Enum):
    SHIP = "ship"
    PICKUP = "pickup"
    STORE = "store"            # in-store, includes store name in `detail`

@dataclass
class Reading:                 # what every poller/tracker returns, one per listing checked
    retailer: str              # "bestbuy", "sony", ...
    state: StockState
    layer: Layer
    url: str                   # direct listing link, tap-to-buy
    price_cents: int | None
    seller: str | None         # "Sold by retailer" or marketplace seller name
    fulfillment: Fulfillment | None
    detail: str | None         # store name, SKU/bundle name, or error text
    at: float                  # unix timestamp
```

**Settings (`settings.json`)** shape. All keys optional with defaults. Validate on load, fail with a plain-English message naming the bad key.

```json
{
  "msrp_cents": 89999,
  "tolerance_cents": 5000,
  "repeat_seconds": 60,
  "no_poll_alert_minutes": 10,
  "zip": "98036",
  "radius_miles": 10,
  "quiet_hours": [],
  "retailers": { "bestbuy": { "enabled": true, "interval_seconds": 45 } },
  "channels": {
    "ntfy":   { "enabled": true,  "server": "https://ntfy.sh", "alert_topic": "", "ack_topic": "" },
    "discord":{ "enabled": false, "webhook_url": "" },
    "telegram":{ "enabled": false, "bot_token": "", "chat_id": "" },
    "sms":    { "enabled": false, "gateway_address": "" },
    "pc":     { "enabled": true }
  },
  "dashboard": { "host": "127.0.0.1", "port": 8765 }
}
```

`quiet_hours` item: `{ "days": [0,1,2,3,4,5,6], "start": "23:00", "end": "07:00", "mode": "mute" }` (`mode`: `mute` or `downgrade`). Empty list = nothing muted.

**Notifier protocol:**
```python
class Notifier(Protocol):
    name: str
    async def send(self, alert: "Alert") -> None: ...   # must raise on failure; fan-out catches and logs
```

**Alert** = `{ event_id, loud: bool, rows: list[Reading] sorted by price then detection time, test: bool }`. Each row renders: retailer, price vs MSRP (e.g. `$899.99, at MSRP` or `$1,049.99, +$150`), seller label, fulfillment, detection layer, link.

---

## 4. Phases

Each phase ends in something the owner can run. Do not start phase N+1 until phase N's checks pass.

### Phase 1: Skeleton, config, storage, test event

**Goal:** `python -m shelf_scout` starts, loads settings, logs clearly, and can create a fake detection.

**Build:**
- `pyproject.toml` with deps. `.gitignore`. `settings.example.json`. `README.md` stub.
- `models.py` per section 3.
- `config.py`: load, validate, defaults, atomic save (write temp + rename). Plain-English validation errors.
- `db.py`: SQLite tables: `readings` (latest per retailer), `events` (restock event: id, retailer, started, ended, price, seller, acked_at), `health` (retailer, last_ok, error_count, state, note), `announcements`. Create-if-missing on startup.
- `__main__.py`: logging to console and `logs/shelf_scout.log` (rotating). Starts an asyncio loop (nothing else yet).
- `engine.fake_reading()` helper that builds a test `Reading` (used by test mode later).

**Done when:**
- `python -m shelf_scout` runs, prints "loaded settings", creates the DB, exits cleanly on Ctrl+C.
- Bad `settings.json` (e.g. `"tolerance_cents": "abc"`) prints a message naming the key.
- `pytest tests/test_config.py` passes (defaults, validation, atomic save).

---

### Phase 2: Alert engine + notifiers + acknowledge (the whole alert path, with fake data)

**Goal:** a fake in-stock event reaches every enabled channel, repeats every 60 s, and stops when acked from the phone or PC. This is the most valuable phase. Prove it before writing any scraper.

**Build:**
- `engine.py`:
  - `handle_reading(reading)`: tracks last known state per `(retailer, listing url)`. On `OUT/ERROR/unknown -> IN_STOCK` open a new event. On `IN_STOCK -> OUT` close the event. Repeated `IN_STOCK` readings do **not** create new alerts (dedupe).
  - Tier: `price_cents <= msrp + tolerance` = loud, else quiet. Unknown price on an in-stock reading = loud (speed over accuracy), label price as "unknown".
  - Combine: if several open events are unacked, one alert lists all rows ranked by price then detection time.
  - Repeat loop: loud + unacked = resend every `repeat_seconds`. Quiet = send once.
  - Quiet hours: `mute` suppresses sends, `downgrade` turns loud into one quiet message. Empty = no effect. (Default for open question: loud tier does NOT override quiet hours; make this a setting `quiet_hours_loud_override: false`.)
  - `ack(event_id=None)`: stops repeats for that event (or all active). Records `acked_at`.
  - Fan-out: send to all enabled notifiers concurrently. One failing channel never blocks the others. Log which channel failed and why.
- `notifiers/ntfy.py`: POST to `{server}/{alert_topic}` with title, body, `Click` header = listing link, `urgent` (priority 5) for loud and `low` for quiet (on Android, urgent can bypass Do Not Disturb once the owner enables that for the ntfy channel; note this in the README), and an **Acknowledge** action button that publishes `ack:<event_id>` to `ack_topic`.
- Ack listener: background task subscribing to `{server}/{ack_topic}/json` (long-lived stream, auto-reconnect with backoff). On `ack:<event_id>` call `engine.ack`.
- `notifiers/chat.py`: Discord webhook POST; Telegram `sendMessage`.
- `notifiers/sms.py`: send email to the configured gateway address (T-Mobile: `<number>@tmomail.net`) via `smtplib` using Gmail SMTP and an app password stored in settings (`channels.sms`: `gateway_address`, `smtp_host`, `smtp_user`, `smtp_password`). If not configured, log "SMS skipped: not configured" and move on. Best effort only; messages must be short (under ~160 chars, include the link).
- `notifiers/pc.py`: loud sound + desktop popup. Use `notify-send` plus a bundled short alarm played with `paplay`/`aplay`/`ffplay` (whichever exists). Log a clear message if none are found.
- CLI: `python -m shelf_scout test` fires a fake loud event (and `--quiet` fires a fake over-cap event) through the real pipeline, marked `test: true` in the title.

**Done when:**
- `python -m shelf_scout test` produces: a DB event row, a phone push with working Link and Acknowledge button, a Discord/Telegram message (if enabled), the PC alarm.
- Without acking, the alert repeats at the configured interval. Tapping Acknowledge on the phone stops it within one interval.
- Two fake retailers in stock produce one combined alert, cheaper first.
- `--quiet` produces a single low-priority notification and no repeat.
- `pytest tests/test_engine.py` covers: dedupe, re-arm after out-and-back, tier boundary (`== cap` is loud), quiet hours (overnight window, empty list), combine ranking, ack.

---

### Phase 3: Poller framework + health/back-off + first three retailers

**Goal:** real stock readings from Sony Direct, Best Buy, Amazon flowing into the engine.

**Build:**
- `pollers/__init__.py`:
  - `Poller` base class: `retailer`, `async check() -> list[Reading]`. Subclasses only implement `check`.
  - Runner per enabled retailer: loop with `interval_seconds` +/- ~20% random jitter. Calls `engine.handle_reading` for each reading.
  - Detection of blocks: HTTP 403/429/503, CAPTCHA/"robot check" page markers, redirect to a challenge page. Treat as `Reading(state=ERROR, detail="blocked: ...")`.
  - Back-off: on block, double the wait each time (cap 30 min), reset on success. Notify the owner **once per block event** (not per retry). Show state in `health` table.
  - Heartbeat: update `health.last_ok` on every successful (non-error) poll.
  - Plain `httpx` client with a normal, honest `User-Agent` and sane timeouts. No spoofing, no proxies.
- Each retailer module: **discover the data source first.** Order of preference per the PRD: (1) the retailer's own JSON/availability endpoint if one exists and is stable, (2) the product page. Return both layers when both work (`Layer.ENDPOINT` and `Layer.PAGE`). Fastest signal wins; do not wait for the other.
- Put product URLs/SKUs in `settings.json` under each retailer (`"urls": [...]`, `"skus": [...]`), not hardcoded, so the owner can fix a dead link without editing code.
- Parse: stock state, price, seller (first-party vs marketplace; Amazon "Ships from / Sold by"), fulfillment (ship/pickup).
- Fixture tests: save a real in-stock page and a real out-of-stock page per retailer into `tests/fixtures/<retailer>/`. Parser tests assert both, plus a garbage page that must yield `ERROR`, not `OUT_OF_STOCK`.

**Done when:**
- `python -m shelf_scout poll-once bestbuy` prints the current `Reading`(s) from the live site. Same for `sony`, `amazon`.
- Running the full service for 10 minutes shows steady heartbeats in the log and `health` table.
- Simulating a 429 (unit test or local stub server) triggers back-off, one notification, and recovery.
- Parser tests pass, including the garbage-page-is-ERROR case.

**Reality check for the builder:** retailer sites change and may block. If a source can't be read reliably, say so plainly, ship the best working layer, and rely on the tracker layer (Phase 5). Do not evade.

---

### Phase 4: Remaining core retailers + local stock

**Goal:** all six PRD core retailers plus Costco are polled. Local stock works where exposed.

**Build:**
- `walmart.py`, `target.py`, `gamestop.py`, `costco.py` using the Phase 3 pattern. Label marketplace sellers (Walmart).
- Local stock for retailers that expose per-store data (Best Buy, Target, GameStop, Walmart are the likely ones): query by `zip` + `radius_miles` from settings. Emit `Fulfillment.STORE` or `PICKUP` readings with the store name in `detail`. If a retailer doesn't expose it, silently fall back to the online listing and note it on the dashboard health panel.
- Record in `README.md` a short table: retailer, data source used, local stock supported yes/no. (This answers the PRD open question about per-store data.)
- Optional retailers (Micro Center, Newegg, B&H, Adorama) are **not** in this phase. They are Phase 2 of the PRD.

**Done when:**
- `poll-once <retailer>` works for all of: sony, bestbuy, amazon, walmart, target, gamestop, costco.
- Each retailer has parser fixture tests (in, out, garbage).
- The README table is filled in with what was actually found.

---

### Phase 5: Tracker/feed layer + events and announcements

**Goal:** an independent signal that keeps working when retailer polling is blocked, plus a sales/announcement feed.

**Build:**
- `trackers/feeds.py`: poll free sources and convert hits into `Reading(layer=TRACKER, ...)`. Candidates from the PRD: Trackalacker PS5 Pro page, RSS feeds of restock communities. Check each source's free-tier limits and terms first; use only what is clearly free and permitted. Make the feed list a settings key (`"feeds": [{ "name", "url", "type": "rss|html" }]`).
  - A tracker hit has no trustworthy price/seller. Label it "unverified (tracker)" and send it as loud. The detection layer is shown on the alert so the owner can judge.
- `trackers/events.py`: ship a small static sale calendar (Black Friday, Cyber Monday, holiday periods for the current year) in a JSON file plus an RSS/announcement fetch (Sony blog, retailer news) into the `announcements` table. Optional heads-up notification (setting, off by default).

**Done when:**
- With retailer pollers disabled, a tracker hit alone produces a full loud alert.
- Dashboard data source (`announcements` + calendar) returns upcoming events sorted by date.
- Tracker failure shows as an error in `health`, never as "no stock".

---

### Phase 6: Dashboard and settings UI

**Goal:** the owner changes every setting and sees live status in a browser. Zero code edits needed.

**Build** (`web/app.py` + templates, started in the same process as the service):
- **Dashboard (`/`)**, auto-refresh every ~5 s (simple polling `fetch`, no websockets):
  - Live stock per retailer: in stock / out of stock / error (color + text, not color alone).
  - Price vs MSRP with the difference.
  - Restock history table: retailer, time, duration in stock, price, seller.
  - Bot health: last good poll, error count, back-off/block state per retailer.
  - Upcoming events and announcements.
  - **Acknowledge** button (active alert), **Test mode** button, **Stop everything** button (pauses all pollers and repeat alerts; a matching **Resume**).
- **Settings (`/settings`)**: form for every key in section 3: MSRP, tolerance, computed cap, quiet hours editor, retailers on/off + interval + URLs, channels on/off + topics/webhooks/tokens, repeat interval, no-poll alert minutes. Save writes `settings.json` atomically and **applies without a restart** (engine and pollers re-read config on change).
- Bind to `127.0.0.1` by default. Mask secrets in the UI (show last 4 chars; blank means unchanged). No auth in v1 since it is local-only; if `host` is changed to non-loopback, log a loud warning.

**Done when:**
- Every panel above renders with real data from a running service.
- Changing tolerance in the UI changes the next alert's tier without a restart.
- Test mode button produces the full Phase 2 result.
- Stop everything stops polling and repeats; Resume restores them.

---

### Phase 7: Reliability, quiet hours polish, systemd

**Goal:** it runs for weeks unattended and tells the owner when it can't.

**Build:**
- **No-successful-poll alert:** if a retailer (or all sources overall) has had no successful poll for `no_poll_alert_minutes` (default 10), send one notification, then once more on recovery. No spam.
- Global "bot is blind" alert: if *every* source is erroring.
- Startup self-check: log which channels are configured, which retailers have URLs, and warn clearly about anything missing (empty ntfy topic, etc.).
- Crash safety: top-level handler per poller task so one poller crashing restarts only that poller (log + back-off), never the whole service.
- `deploy/shelf-scout.service` (systemd **user** unit: `Restart=always`, `RestartSec=5`, working dir, `ExecStart` using the venv python). Include `loginctl enable-linger` note in the README so it survives logout/reboot.
- Log rotation already in place from Phase 1; confirm size cap.
- README "Troubleshooting" section: top 5 failure modes in plain English (no alerts arrive, phone ack not working, retailer shows error, service not starting, dashboard unreachable) with the exact command for each.

**Done when:**
- Kill the process: systemd restarts it within seconds.
- Cut network for 11 minutes (or shorten the setting for the test): exactly one "can't poll" alert, one recovery alert.
- A poller forced to raise an exception keeps the other pollers running.

---

### Phase 8: End-to-end test and handoff

**Goal:** the owner is confident the tool will fire at the real drop.

**Build / run:**
- Final README: install, configure, start, test, update product URLs, stop.
- `python -m shelf_scout doctor`: prints a pass/fail list: settings valid, DB writable, each channel sends a test ping, ack topic reachable, each retailer returns a non-error reading, systemd unit active.
- Full dress rehearsal checklist in README, owner runs it:
  1. `doctor` all green.
  2. Test mode: confirm push, chat, PC alarm, repeat, phone ack.
  3. Leave it running 24 h; check the dashboard health panel for errors.

**Done when:** `doctor` is green (or each failure has a plain-English fix), and the owner confirms the test alert arrived on their phone and the ack worked.

---

## 5. After v1 (do NOT build unless the owner asks)

PRD "Phase 2 / later": auto-scan for new retailers and listings, restock pattern predictions, optional retailers (Micro Center, Newegg, B&H, Adorama), Tailscale remote dashboard. Browser automation beyond a direct link stays **out of scope**.

---

## 6. Defaults chosen for PRD open questions

| Open question | Default used | Easy to change? |
| --- | --- | --- |
| Free SMS route | Owner is on T-Mobile (Android). Try the email-to-SMS gateway `<10-digit-number>@tmomail.net`, sent through the owner's free Gmail via SMTP app password. Unverified that T-Mobile still delivers it: `doctor` must test it and report plainly. If dead, SMS stays off. There is no free official SMS API and Google Messages has no send API. The real backstop is ntfy urgent priority (see Phase 2). | Yes, `channels.sms` |
| Per-store stock near Lynnwood | Build per retailer if exposed; fall back to online listing; document result in README | Yes, per-retailer |
| Auto-scan / predictions in v1? | No, Phase 2 | n/a |
| Default quiet hours | None set (nothing muted). Loud tier does not override a schedule once one is set (owner confirmed). Must be a toggle in the Settings UI. | Yes, UI + `quiet_hours_loud_override` (default `false`) |

---

## 7. Definition of done for the whole project

- Fake restock reaches phone, chat and PC; repeats; phone ack stops it.
- Real readings from all seven core retailers (or a documented reason one is tracker-only).
- Settings all editable in the UI, applied live.
- Runs as a self-restarting service and reports its own health.
- No credentials stored; no evasion code anywhere.

---

## 8. Quick risk reminders (builder)

- A silent false "out of stock" is the worst failure. When unsure, return `ERROR`.
- Retailers change pages. Keep selectors/URLs/SKUs in one obvious place per retailer, with a comment saying how to re-find them.
- Speed matters: do not add confirmation checks or artificial delays before alerting.
- Alerts must include the direct listing link. Always.

## 9. Owner-only (Phase 0, no code)

Check stock/price at Sony, Best Buy, Amazon first; create retailer accounts with saved payment/shipping and stay logged in; install ntfy and subscribe to a **random, hard-to-guess** alert topic and ack topic; create Discord server or Telegram bot; sign up for retailer notify-me alerts; set up Trackalacker/StockDrops/Reddit/@Wario64 as a parallel safety net.

## Parked

(Empty. Add out-of-scope ideas here instead of building them.)
