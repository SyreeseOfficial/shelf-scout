"""`python -m shelf_scout` starts the service."""
import argparse
import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import httpx
import uvicorn

from . import config, db, doctor, pollers
from .trackers.feeds import build_feed_pollers
from .watchdog import Watchdog, startup_check
from .web.app import create_app
from .engine import Engine
from .models import StockState
from .notifiers.ntfy import ack_listener

# Paths are anchored to the repo, not the current directory, so it works the same under systemd.
ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = ROOT / "settings.json"
DB_PATH = ROOT / "shelf_scout.db"
LOG_DIR = ROOT / "logs"

log = logging.getLogger("shelf_scout")


def setup_logging() -> None:
    LOG_DIR.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    # Cap: 1 MB x 3 backups, so logs never grow past ~4 MB.
    handlers = [logging.StreamHandler(), RotatingFileHandler(LOG_DIR / "shelf_scout.log", maxBytes=1_000_000, backupCount=3)]
    for h in handlers:
        h.setFormatter(fmt)
    logging.basicConfig(level=logging.INFO, handlers=handlers)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # its INFO lines print request URLs, which can contain the Best Buy API key


async def serve_dashboard(engine: Engine, conn) -> None:
    """The dashboard runs inside this same process and event loop. If it can't start, alerts keep working."""
    host, port = engine.settings["dashboard"]["host"], engine.settings["dashboard"]["port"]
    if host not in ("127.0.0.1", "localhost", "::1"):
        log.warning("DASHBOARD IS EXPOSED: host is %r, not 127.0.0.1. There is no login, so anyone who can reach "
                    "%s:%s can read and change your settings (including secrets). Set dashboard.host back to 127.0.0.1.", host, host, port)
    app = create_app(engine, conn, SETTINGS_PATH)
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
    server.install_signal_handlers = lambda: None  # Ctrl+C is handled by main(); uvicorn must not grab it
    try:
        log.info("dashboard at http://%s:%s/", host, port)
        await server.serve()
    except (SystemExit, OSError) as e:  # uvicorn exits (not raises) when the port is taken
        log.error("dashboard could not start on %s:%s (%s). Is another program using that port? "
                  "Alerts still work; change dashboard.port in settings.json and restart.", host, port, e)


async def run(settings: dict) -> None:
    conn = db.connect(DB_PATH)
    engine = Engine(settings, conn)
    for level, msg in startup_check(settings):
        getattr(log, level)("self-check: %s", msg)
    asyncio.create_task(ack_listener(engine))
    asyncio.create_task(serve_dashboard(engine, conn))
    asyncio.create_task(Watchdog(engine).run())
    started: set[str] = set()   # retailers / feeds that already have a poller task
    async with httpx.AsyncClient(headers={"User-Agent": pollers.USER_AGENT}, timeout=15, follow_redirects=True) as client:
        while True:
            # Re-checked every few seconds so a retailer or feed switched on (or added) in Settings starts without a restart.
            for name, cfg in engine.settings["retailers"].items():
                if name in started or not cfg["enabled"]:
                    continue
                started.add(name)
                poller = pollers.build(name, client, lambda: engine.settings)
                if poller is None:
                    log.info("%s: no poller built yet, skipping", name)
                    continue
                asyncio.create_task(pollers.run_poller(poller, engine, conn))
                log.info("%s: polling every ~%ss", name, cfg["interval_seconds"])
            for poller in build_feed_pollers(client, lambda: engine.settings, conn, engine.notice):
                if poller.retailer in started or not poller.enabled:
                    continue
                started.add(poller.retailer)
                asyncio.create_task(pollers.run_poller(poller, engine, conn))
                log.info("feed %s: checking every ~%ss (%s)", poller.retailer, poller.cfg["interval_seconds"], poller.cfg["role"])
            await asyncio.sleep(5)


async def poll_once(settings: dict, retailer: str) -> int:
    """Check one retailer right now and print what it says. No alerts, nothing saved."""
    async with httpx.AsyncClient(headers={"User-Agent": pollers.USER_AGENT}, timeout=15, follow_redirects=True) as client:
        poller = pollers.build(retailer, client, lambda: settings)
        if poller is None:
            print(f"No poller for {retailer!r} yet. Available: sony, bestbuy, amazon, walmart, target, gamestop, costco")
            return 1
        try:
            readings = await poller.check()
        except pollers.PollError as e:
            readings = [poller.error("", e)]
    for r in readings:
        price = f"${r.price_cents / 100:,.2f}" if r.price_cents is not None else "price unknown"
        print(f"{r.state.value.upper():<13} {r.retailer} [{r.layer.value}] {price} | {r.seller} | {r.fulfillment.value if r.fulfillment else '-'} | {r.detail}\n{'':14}{r.url}")
    return 1 if all(r.state is StockState.ERROR for r in readings) else 0


async def run_test(settings: dict, quiet: bool) -> None:
    """Push one fake restock through the real pipeline: DB, every enabled channel, repeats, ack."""
    engine = Engine(settings, db.connect(DB_PATH))
    listener = asyncio.create_task(ack_listener(engine))
    try:
        await engine.fire_test(quiet)
        if quiet:
            log.info("quiet test sent: one low-priority message, no repeat")
    finally:
        listener.cancel()


def main() -> int:
    parser = argparse.ArgumentParser(prog="shelf_scout")
    sub = parser.add_subparsers(dest="command")
    test = sub.add_parser("test", help="fire a fake restock through every enabled channel")
    test.add_argument("--quiet", action="store_true", help="fake an over-cap price (one low-priority message)")
    once = sub.add_parser("poll-once", help="check one retailer now and print the result")
    once.add_argument("retailer", help="sony, bestbuy, amazon, walmart, target, gamestop, costco")
    sub.add_parser("doctor", help="check that everything needed for a real alert works (sends a test ping to each channel)")
    args = parser.parse_args()
    setup_logging()
    try:
        settings = config.load(SETTINGS_PATH)
    except config.ConfigError as e:
        log.error("%s", e)
        return 1
    if SETTINGS_PATH.exists():
        log.info("loaded settings from %s", SETTINGS_PATH)
    else:
        log.info("loaded settings: no settings.json found, using defaults (copy settings.example.json to change them)")
    db.connect(DB_PATH).close()
    log.info("database ready at %s", DB_PATH)
    try:
        if args.command == "doctor":
            return doctor.report(asyncio.run(doctor.run_doctor(settings, DB_PATH)))
        if args.command == "poll-once":
            return asyncio.run(poll_once(settings, args.retailer))
        asyncio.run(run_test(settings, args.quiet) if args.command == "test" else run(settings))
    except KeyboardInterrupt:
        log.info("stopped (Ctrl+C)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
