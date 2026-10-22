# PS5 Pro Stock Alert Tool: PRD

Oct 21, 2026 · @Syreese Delos Santos

## Overview

This tool watches major US retailers for a PS5 Pro in stock and alerts the owner within about a minute, so they can buy at MSRP ($899.99) before scalpers do. It is a personal, free, locally run alert system, not a purchasing bot.

**Problem.** Scalpers grab PS5 Pro stock and resell it at a markup. The owner wants exactly one console at MSRP and nothing more.

**Product.** A Python app on the owner's always-on Linux PC polls retailer product pages, retailer data endpoints and third-party trackers every 30 to 60 seconds. When a Pro shows as in stock, it sends alerts on every free channel (phone push, text, Discord or Telegram, loud PC alarm), repeats them every minute until acknowledged, and includes a direct link to the listing. The owner taps the link and completes checkout themselves. A local browser dashboard shows live status and holds every setting.

**Alternatives considered.**

- Full auto-checkout bot: rejected. Retailers use bot defenses (Akamai, Cloudflare, queues, CAPTCHAs, device fingerprinting), scalpers run better-equipped operations, and automated checkout violates retailer terms, risking canceled orders and banned accounts.
- Existing free trackers alone: adopted as a parallel safety net rather than a replacement (see Setup checklist and free companion tools).
- Checking whether a bot is needed at all: recommended before building, because MSRP stock may already be obtainable from Sony Direct, Best Buy or Amazon.

## Goals and non-goals

The single goal is buying one PS5 Pro at MSRP as soon as possible; every other requirement supports that.

**Goals**

1. Buy one PS5 Pro at MSRP ($899.99), or within the owner's chosen tolerance, ASAP.
2. Detect in-stock listings within one polling cycle (30 to 60 seconds) at every monitored retailer.
3. Reach the owner on every free channel, and keep alerting every minute until acknowledged.
4. Keep the owner in control of the purchase: the tool sends a direct link, and the owner clicks Buy.
5. Store no credentials and automate nothing inside a retailer account.
6. Cost nothing: free software, free hosting (the owner's PC), free notification channels.
7. Run unattended with minimal debugging, and report its own health.
8. Make every tunable value (price cap, quiet hours, retailers, channels) editable in the UI.

**Non-goals**

- Automated add-to-cart or checkout of any kind (dropped; see Decisions log).
- Proxy rotation, user-agent spoofing, CAPTCHA solving or any other evasion.
- Buying more than one unit, or reselling anything.
- Paid services, paid hosting or paid alert tiers.
- A mobile app, cloud deployment or non-US retailers.
- Auto-stopping after a purchase (the owner stops it manually).
- A second verification check before alerting (speed beats accuracy here).

## User and context

The only user is the owner, a US buyer in the Lynnwood, WA area who wants a working tool this week and little debugging.

- **Location and market:** US, Lynnwood, WA area. Pricing and retailers are US only.
- **Availability:** Often away from the PC but with the phone in hand. When alerted, the owner can act within a minute.
- **Equipment:** An always-on, always-online Linux PC runs the tool. A phone handles remote alerts and acknowledgements.
- **Memberships:** Amazon Prime only. No Best Buy membership, Walmart+ or Target Circle.
- **Technical level:** Android development background, but wants the tool to "just work" with minimal debugging. The tool is built by vibe coding, so code should be simple, well-commented and self-diagnosing.
- **Accounts:** The owner will create accounts with saved payment and shipping info at every retailer on the list, and stay logged in on the browser they will use to check out.
- **Urgency:** ASAP. Phase 1 should be usable as soon as possible.

## Success criteria

The project succeeds when the owner buys a PS5 Pro at MSRP, and then it is done.

The following proposed targets support that outcome. They are suggestions for the build, not figures the owner has set:

- Detection delay is no longer than one polling interval (60 seconds worst case) per retailer.
- Alerts go out on every enabled channel within a few seconds of detection.
- An in-budget alert repeats every 60 seconds until the owner acknowledges it.
- The tool alerts the owner if it has been unable to poll successfully for an extended period (default 10 minutes, configurable).
- A fake in-stock event proves every channel and the acknowledge path work before any real drop.

## Retailers in scope

The tool monitors six core retailers plus a longer optional list, and treats "whoever can sell a PS5 Pro" as in scope through third-party trackers.

| Retailer | Tier | Fulfillment | Notes |
| --- | --- | --- | --- |
| Sony PlayStation Direct | Core | Ship | Highest priority; first-party MSRP |
| Best Buy | Core | Ship and pickup | No membership; check nearby stores |
| Amazon | Core | Ship | Owner has Prime; watch seller label (first-party vs marketplace) |
| Walmart | Core | Ship and pickup | Marketplace sellers possible; label seller |
| Target | Core | Ship and pickup | Check nearby stores |
| GameStop | Core | Ship and pickup | Check nearby stores |
| Costco | Core | Ship and pickup | Owner has membership |
| Sam's Club | Skip | Ship and pickup | Membership required |
| Micro Center | Optional | In-store only | Local stock only |
| Newegg | Optional | Ship | Marketplace sellers possible; label seller |
| B&H Photo | Optional | Ship | |
| Adorama | Optional | Ship | |

**Local stock.** The tool also checks in-store availability within 10 miles of Lynnwood for retailers that expose it. What it can see depends on what each retailer publishes; where per-store data is unavailable, it falls back to the online listing.

**Fulfillment.** Shipping and in-store pickup are both acceptable, whichever is available.

**Accounts.** The owner will set up an account with saved payment and shipping info at every retailer above and stay logged in on the checkout browser. The tool itself never touches these accounts.

## Product and pricing rules

Any new PS5 Pro counts, and the loud alert fires for anything at or under MSRP plus the owner's tolerance; everything else still alerts, but quietly.

| Rule | Setting |
| --- | --- |
| Product | Any PS5 Pro SKU; console alone or an MSRP bundle |
| Condition | New only (used and refurbished are out of scope) |
| MSRP | $899.99 (confirmed current by the owner; the launch price was $699.99) |
| Tolerance | Owner will pay up to $25 to $50 over MSRP; default $50, editable in the UI |
| Default cap | $949.99 (MSRP plus default tolerance), editable in the UI |
| Region | US |
| Seller handling | Alert on every listing and label the seller; do not filter marketplace sellers out |
| Loud tier | At or under the cap: repeating alert on all channels |
| Quiet tier | Over the cap: single low-priority notification, no repeat |

Bundles are judged by their total price against the same cap. Because every seller alerts, the label ("Sold by retailer" vs a named marketplace seller) is what lets the owner skip scalper listings in a glance.

## Stock detection

The tool combines three detection layers and takes the fastest signal from any of them.

1. **Product-page polling.** Fetch each retailer's product page and parse stock state, price, seller and fulfillment options.
2. **Retailer data endpoints.** Where a retailer exposes stock or price as JSON or an API, use it for faster, cleaner reads. These can change without notice, so the page layer stays as a backup.
3. **Third-party trackers and feeds.** Watch free tracker alerts, RSS and restock communities as an independent signal.

**Polling rate.** Every 30 to 60 seconds per retailer. A small random jitter is recommended so requests don't look mechanically regular. The rate is editable per retailer in the UI.

**No verification delay.** The tool alerts the moment any layer reports stock. It does not wait for a second confirming check, accepting some false alarms in exchange for speed. Each alert states which layer detected the stock so the owner can judge confidence.

**De-duplication.** One restock event per retailer produces one alert sequence. Repeats come only from the escalation rule, not from re-detection. A fresh out-of-stock to in-stock transition starts a new event.

**Data captured per detection:** retailer, listing URL, price, seller, fulfillment (ship, pickup, store), detection layer, and timestamp. This feeds the dashboard and restock history.

**Events and announcements.** The tool also tracks upcoming sales and drops: a calendar of known sales periods such as Black Friday and the holidays, plus announcements from Sony and retailers. These appear on the dashboard and can optionally trigger a heads-up notification.

## Alerts and escalation

Every in-budget detection fires on every enabled channel at once and repeats every 60 seconds until the owner acknowledges it. The owner asked for as many alert forms as possible, with the constraint that the tool must be free.

| Channel | Role | Cost note |
| --- | --- | --- |
| ntfy | Primary phone push, with an acknowledge button | Free |
| Text message | Best-effort SMS | Free options are limited; use the cheapest free route that works (for example an email-to-SMS gateway if the owner's carrier supports it), otherwise rely on the other channels |
| Discord or Telegram | Secondary phone and desktop alert | Free |
| Loud PC alarm | Sound and popup when the owner is at the computer | Free |
| Pushover | Optional alternative to ntfy | As far as I know it is paid after a trial, so ntfy is the default |

**Escalation rules**

- In-budget alerts repeat every 60 seconds on all channels until acknowledged.
- Over-cap alerts send once, quietly, with no repeat.
- If several retailers are in stock at once, send one combined alert ranked by price, then by detection speed, with a direct link for each.
- Each alert shows retailer, price versus MSRP, seller label, fulfillment option, detection layer and the direct listing link.
- Acknowledging stops repeats for that restock event. A new out-of-stock to in-stock transition re-arms the alert.

**Quiet hours.** A configurable schedule in the UI (days and times) controls when alerts are muted or downgraded. With no schedule set, nothing is muted.

## Local dashboard and settings

A small web page served from the owner's PC shows live status and holds every setting, so no one edits code to change behavior.

**Dashboard panels**

- **Live stock status:** current state per retailer (in stock, out of stock, error).
- **Price versus MSRP:** the price shown and its difference from $899.99.
- **Restock history:** a log of past restocks with retailer, time, how long it stayed in stock, price and seller.
- **Bot health:** last successful poll per retailer, error counts, and any block or back-off state.
- **Upcoming events:** sale calendar and recent Sony or retailer announcements.

**Settings editable in the UI**

- MSRP value, tolerance and price cap
- Quiet hours schedule
- Retailers on or off, and polling interval per retailer
- Notification channels on or off, with their topics, webhooks or tokens
- Alert repeat interval
- Test mode button (fires a fake in-stock event)
- A manual stop-everything control (there is no auto-stop after a purchase)
- An acknowledge button for the active alert

## Phone and away mode

When the owner is away from the PC, the phone gets a notification with a direct link and can acknowledge the alert without reaching the PC.

1. The bot detects stock and sends the alert, including the direct link to the listing.
2. The owner taps the link on their phone, which opens the retailer page or app where they are already logged in with saved payment, and checks out within about a minute.
3. To stop the repeating alerts, the owner taps an acknowledge button on the ntfy notification.

**How the acknowledge works.** The button publishes a message to a private ntfy topic that the bot is subscribed to. The bot only makes outbound connections, so no ports are opened on the owner's home network and no account or server is needed.

**Optional.** Tailscale (free for personal use) can give the phone secure access to the full dashboard. It is not required for v1.

**Owner setup.** Installing the ntfy app and subscribing to the alert topic takes a few minutes. The owner has said they don't mind setting up things on the phone.

## Reliability, blocking and testing

The tool handles retailer blocking by backing off and reporting, never by evading, so it stays within a safe and free approach. The owner delegated this choice.

**Block handling**

- On a block, rate limit or CAPTCHA page, back off for that retailer with increasing delay, and retry after the cooldown.
- Notify the owner once per block event and show the state on the dashboard.
- No proxies, no spoofed user agents, no CAPTCHA solving.
- If primary sources are blocked, the third-party tracker layer keeps providing a signal.

**Health and uptime**

- Heartbeat per retailer, shown on the dashboard.
- An alert if no successful poll occurs for a configurable period (proposed default: 10 minutes).
- Run as a background service that restarts after a crash or reboot (a systemd service on Linux is recommended).
- Clear logs and plain-language error messages, so debugging stays minimal.
- Parser breakage (a retailer changes its page) is reported as an error rather than silently showing "out of stock".

**Testing**

A test mode fires a fake in-stock event through the whole pipeline: detection record, every notification channel, repeat escalation, and the phone acknowledge button. The owner runs it after setup and again before any known drop.

## Architecture and stack

Everything runs as one Python service on the owner's Linux PC, using only free components.

- **Language and runtime:** Python (recommended and accepted), Linux, run as a background service.
- **Pollers:** one module per retailer, each returning the same record (stock, price, seller, fulfillment, URL) so retailers can be added without touching the rest.
- **Tracker and feed reader:** pulls third-party alerts, RSS and announcement sources.
- **Alert engine:** de-duplicates events, applies price tiers and quiet hours, and runs the 60-second repeat loop until acknowledged.
- **Notifiers:** ntfy, Discord or Telegram, best-effort SMS, and a local PC alarm.
- **Storage:** a small local database or file for restock history, health data and settings.
- **Dashboard:** a lightweight local web app, opened in any browser.
- **Credentials:** none stored. The owner checks out in their own logged-in browser.
- **Browser:** whichever is easiest; the tool only builds links and does not drive the browser.

Data flow (text version of the architecture diagram):

```
Retailer product pages ─┐
Retailer data endpoints ─┼─> Alert engine ─┬─> ntfy phone push ──┐
Trackers and feeds ─────┘   (dedupe, price │  Discord / Telegram ─┤
                             tiers, quiet   │  SMS (best effort) ──┼─> Owner's phone and PC
                             hours, repeat  └─> Loud PC alarm ─────┘   (tap link, buy, acknowledge)
                             every 60 s)  ^
                               │          └── ack via ntfy topic
                               v
                     Dashboard and settings
```

Three signal sources feed one alert engine, which fans out to four notifiers; the owner's phone acknowledge returns through an ntfy topic. No retailer logins are stored; the owner buys in their own browser.

## Security, terms of service and risk

The tool is read-only polling plus alerts and a direct link, which keeps account risk low; the owner chose this over automating add-to-cart or checkout.

**Terms-of-service tradeoffs**

- **Read-only polling and alerts:** lowest risk. Checking public product pages at a polite rate is generally tolerated; the worst case is a temporary IP block.
- **Direct link, owner clicks Buy:** low risk. The owner does the purchase; the tool only saves time.
- **Automated login, add-to-cart or checkout:** violates most retailers' terms, risks canceled orders and banned accounts, and is the hardest part to keep working against bot detection. Not in scope.

**Risks and mitigations**

| Risk | Mitigation |
| --- | --- |
| Retailer blocks or rate-limits the bot | Back off, notify once, rely on the tracker layer, never evade |
| A retailer changes its page and the parser breaks | Report parser errors loudly; never show a silent "out of stock" |
| False alarms from unverified detection | Accepted for speed; label the detection layer on each alert |
| PC or network down | Health alert, auto-restart service, free trackers run in parallel |
| Free SMS is unreliable or unavailable | Treat SMS as best-effort; ntfy, Discord or Telegram and the PC alarm carry the load |
| Scalpers faster than a one-minute response | Parallel free trackers, saved payment and shipping everywhere, direct links |
| Marketplace scalper listings | Seller label on every alert; over-cap alerts are quiet |
| Alert fatigue | Quiet hours, quiet tier, single combined alert for multiple retailers |
| MSRP changes again | MSRP and cap are editable in the UI |

**Secrets.** The only secrets are notification topics, webhooks and tokens, stored in the local settings file on the owner's PC. No retailer credentials or payment data are ever stored.

## Setup checklist and free companion tools

Several free tools can alert the owner today, before the bot exists, and should run alongside it as a safety net.

**Owner checklist**

- [ ] Check current PS5 Pro stock and price at Sony Direct, Best Buy and Amazon
- [ ] Create accounts with saved payment and shipping at the six core retailers (and the optional ones)
- [ ] Stay logged in on the checkout browser
- [ ] Install the ntfy app on the phone and subscribe to the alert topic
- [ ] Create a Discord server or Telegram bot for alerts
- [ ] Sign up for retailer "notify me" and email or text alerts
- [ ] Set up the free trackers below
- [ ] Run the test-mode fake restock once everything is connected

**Free companion tools** (details from search results; confirm current free-tier limits before relying on them)

| Tool | What it does | Note |
| --- | --- | --- |
| [Trackalacker](https://www.trackalacker.com/products/showcase/playstation-5-pro-console) | Free email or text alerts per store listing; its PS5 Pro page tracks 32 listings | Best single baseline |
| [StockDrops](https://www.slashgear.com/tips-for-finding-a-ps5-this-holiday-season-26700521) | Discord server and app with per-product PS5 alerts | Desktop app reportedly fastest |
| Reddit restock communities and X accounts such as @Wario64 | Early restock news | Turn on notifications |
| Retailer "notify me" and email or text alerts | Native alerts at Best Buy, Target, Walmart, GameStop, PlayStation Direct | Sign up everywhere |
| [Distill](https://distill.io/blog/ps5-restock-tracker/) | Page monitor with email, Discord, SMS, phone or desktop alerts | Free tier is limited |
| [PageCrawl](https://pagecrawl.io/blog/receive-notifications-playstation5-track-supply) | Page monitor | Skip: free plan checks about hourly with 220 checks a month, too slow |

## Phasing and timeline

The timeline is ASAP: do the free steps today, ship the core alert tool first, and defer everything that doesn't help buy sooner.

1. **Phase 0, today (no code):** check current stock and price, set up the free companion tools and retailer notify-me alerts, create retailer accounts, install ntfy.
2. **Phase 1, v1 (ASAP):** pollers for the six core retailers, three detection layers, price tiers and seller labels, all alert channels with 60-second repeat and phone acknowledge, local dashboard with settings, quiet hours, health monitoring and back-off, test mode, and the events and announcements feed.
3. **Phase 2, later:** auto-scan for new retailers and listings, restock pattern predictions, optional retailers beyond the core six, and optional Tailscale access to the dashboard.
4. **Revisit only if needed:** any browser automation beyond a direct link (currently out of scope).

**Scope note.** The owner first picked auto-scan and restock predictions for v1. They were moved to Phase 2 because they add complexity without helping the owner buy sooner. The owner can pull them back into v1.

## Decisions log and open questions

Every decision below came from the owner's answers or was delegated to the defaults shown; the cart step changed during the conversation.

| Topic | Decision |
| --- | --- |
| Primary goal | Just buy one PS5 Pro (personal tool, throwaway after) |
| Automation level | Alert plus a pre-filled step, with alert-only as fallback; later simplified to alert plus direct link to the listing |
| Cart step | Changed from browser add-to-cart to a direct link to the listing (easier to build and fulfill) |
| Risk approach | Chose browser add-to-cart at first, then dropped it for the direct link; no checkout automation |
| Retailers | Sony Direct, Best Buy, Amazon, Walmart, Target, GameStop, and whoever else sells a Pro |
| Accounts | Owner sets up accounts and payment at all retailers; Prime only |
| Timeline | ASAP |
| Hosting | Owner's Linux PC, always on and online; tool must be free |
| Notifications | Phone push (ntfy or Pushover), text, Discord or Telegram, loud PC alarm; as many as possible |
| Acceptable purchase | Console or MSRP bundle; any Pro SKU; US |
| Price | MSRP $899.99; up to $25 to $50 over; cap configurable in the UI |
| Response time | Within a minute, phone in hand |
| Skill level and stack | Wants it to just work; Python |
| Interface | Small local dashboard in the browser |
| Detection | Combine page polling, endpoints and trackers; 30 to 60 second interval |
| Block handling | Delegated; back off and notify, no evasion |
| Fulfillment and local stock | Ship or pickup; in-store within 10 miles of Lynnwood |
| Dashboard content | Live stock, price versus MSRP, restock history, bot health |
| Auto-stop | None; owner stops manually |
| Seller filter | Alert on all, label seller; over-cap quiet |
| Multiple retailers | Alert all, ranked by price then speed |
| Escalation | Repeat every minute until acknowledged |
| Accuracy | Alert immediately; no verification |
| Browser, OS | Whatever is easiest; Linux |
| Acknowledge | At the PC or from the phone |
| Away mode | Notify phone with direct link |
| Events | Track sales calendar and Sony or retailer announcements |
| Success | Buy a Pro at MSRP, done |
| Quiet hours | Configurable schedule in the UI |
| Testing | Test mode with a fake in-stock event |
| Secrets | No credentials stored; use the logged-in browser |
| Extras | Auto-scan and predictions chosen for v1, moved to Phase 2 |

**Open questions**

- Which free SMS route works with the owner's carrier, if any?
- Which retailers expose usable per-store stock data near Lynnwood?
- Does the owner want auto-scan and restock predictions pulled back into v1?
- What quiet-hours schedule should be the default, and should the loud tier ever override it?
