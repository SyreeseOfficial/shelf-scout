# TODO: open issues

Found while building Phase 3 (2026-10-22). Owner actions first, then code follow-ups.

## Owner actions

- [ ] **Best Buy API key.** Create a free key at https://developer.bestbuy.com/ and set `retailers.bestbuy.api_key` in `settings.json`. Until then Best Buy shows an error in `health`.
- [ ] **Best Buy SKU.** Find the PS5 Pro SKU (the number after `skuId=` in its product page URL) and set `retailers.bestbuy.skus`. I couldn't find the real one.
- [ ] **Amazon ASIN.** Find the PS5 Pro ASIN (the 10 characters after `/dp/`) and set `retailers.amazon.skus`. `B0DGY63Z2H` came from an old deal post and is unverified.

## Blocked sources (not bypassed on purpose)

- [ ] **Amazon is blocked.** amazon.com serves a bot-check page (HTTP 200) to an honest client, so `poll-once amazon` reports `blocked`. Rely on the tracker layer (Phase 5) and Amazon's own notify-me alerts. Re-test now and then; it may stop blocking.
- [ ] **bestbuy.com drops our connection.** Only the official API works. The Best Buy page layer is not available.

- [ ] **Walmart is blocked.** walmart.com redirects an honest client to `/blocked`. Not bypassed. Rely on the tracker layer and Walmart's own notify-me.
- [ ] **GameStop is blocked.** HTTP 403 bot check. Not bypassed. Same fallback.
- [ ] **Target blocked us once (PerimeterX, HTTP 435)** after about 10 test requests in a few minutes. It cleared by itself and now polls live (5 requests per poll). If it comes back during normal running, lower `MAX_STORES` in `pollers/target.py` or raise `retailers.target.interval_seconds`.

## Owner actions (Phase 4)

- [ ] **GameStop link.** Find the PS5 Pro product link on gamestop.com and put it in `retailers.gamestop.urls`. I couldn't find the real one.
- [ ] **Costco link.** Costco only lists the console in short-lived bundles. Put the link in `retailers.costco.urls` when one is listed.
- [ ] **Walmart item id.** Default `11839818124` came from a web search. Confirm it is the plain PS5 Pro console.

## Phase 5 notes

- [ ] **Tracker alerts untested against a real restock post.** Feed parsing is tested on real feed captures, but the "PS5 Pro + restock word" match was only exercised with made-up titles. Watch what lands in the log after the first real drop and tune `RESTOCK` in `trackers/feeds.py`.
- [ ] **Reddit rate-limits intermittently** (403/429 after bursts). The back-off handles it, but if Reddit blocks often, raise that feed's `interval_seconds`.
- [ ] **Trackalacker not used** (no feed, JavaScript page). Not scraped; use its own email/text alerts.
- [ ] **Sale calendar covers 2026 only.** Add 2027 dates to `shelf_scout/trackers/sale_calendar.json` before January.

## Phase 8 notes

- [ ] **Owner sign-off still needed** (the plan's last check): run the dress rehearsal in the README, and confirm a test alert reached your phone and the ack worked. I can't see your phone.
- [ ] **`doctor` pings are real.** It sends a quiet "doctor ping" to each enabled channel, including SMS if on.
- [ ] **Reddit feed often answers 403** to `doctor` and the service (it did once for `curl` too, then worked). It backs off and retries, but it may be an unreliable tracker source. Slickdeals and the PlayStation Blog work.

## Phase 7 notes

- [ ] **The unit file is tested with a temporary systemd unit, not installed.** The real install (README, "Run it as a service") is yours to run. I did not enable anything on your machine.
- [ ] **Desktop popup/alarm from the service** (`notify-send`, `paplay`) depends on the user session's environment. If the PC channel is silent under systemd but works in a terminal, run `systemctl --user import-environment WAYLAND_DISPLAY DISPLAY` and restart.
- [ ] **The 11-minute network-cut check** is covered by unit tests with a fake clock, not by really unplugging the network.

## Phase 6 notes

- [ ] **Look at the dashboard in a real browser.** Tests cover the data and forms, and the pages return 200 with no template errors, but I haven't eyeballed the layout. Open http://127.0.0.1:8765/ and /settings and tell me what looks wrong.
- [ ] **"Stop everything" is not remembered across restarts** (it is in memory only). Tell me if you want it saved.
- [ ] **A secret can't be cleared from the UI** (blank means "keep"). To remove one, edit `settings.json` or turn the channel off.
- [ ] **Renaming a feed** starts a new feed; the old one goes idle until restart.

## Untested against live sites

- [ ] **Target in-stock case.** `tests/fixtures/target/in_stock.json` and `nearby.json` are hand-written from the real out-of-stock reply. Check against a real in-stock reply when one exists.
- [ ] **Walmart / GameStop / Costco parsers** (`pollers/jsonld.py`) use hand-written fixtures. They assume each page carries schema.org JSON-LD `Product` data; unconfirmed on the live sites.
- [ ] **No local stock for Walmart, GameStop, Costco** (nothing exposed that we can read). Only Target has it.
- [ ] **Amazon parser** (`pollers/amazon.py`) uses hand-written in/out fixtures. Check it against a live in-stock and out-of-stock page if Amazon ever lets us read one.
- [ ] **Best Buy parser** (`pollers/bestbuy.py`) uses hand-written fixtures shaped like the API docs. Check it against a real API reply once the key is set (`python -m shelf_scout poll-once bestbuy`).
- [ ] **Sony in-stock case on the PS5 Pro itself.** The in-stock fixture is the real response for a different product (the disc drive), because the Pro is out of stock right now. Re-capture when the Pro is in stock.

## Gaps vs BUILD_PLAN.md

- [ ] **Phase 3 "10 minute run" check.** I ran the full service for about 3 minutes. Do a 10 minute run and look at the health panel.
- [ ] **Sony page layer skipped.** The page HTML has no stock state (JavaScript fills it in and "Add to Cart" is always present), so only the endpoint layer exists.
