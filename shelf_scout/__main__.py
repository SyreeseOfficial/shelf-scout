"""`python -m shelf_scout` starts the service."""
import argparse
import asyncio
import dataclasses
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import config, db
from .engine import Engine, fake_reading
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


async def run(settings: dict) -> None:
    # Later phases start pollers and the dashboard here.
    engine = Engine(settings, db.connect(DB_PATH))
    asyncio.create_task(ack_listener(engine))
    await asyncio.Event().wait()


async def run_test(settings: dict, quiet: bool) -> None:
    """Push one fake restock through the real pipeline: DB, every enabled channel, repeats, ack."""
    engine = Engine(settings, db.connect(DB_PATH))
    listener = asyncio.create_task(ack_listener(engine))
    # A quiet test needs a price just over the cap; a loud one sits right at MSRP.
    reading = fake_reading(price_cents=config.cap_cents(settings) + 10000 if quiet else settings["msrp_cents"])
    try:
        await engine.handle_reading(reading, test=True)
        if quiet:
            log.info("quiet test sent: one low-priority message, no repeat")
        else:
            log.info("loud test sent. It repeats every %ss until you tap Acknowledge on your phone (Ctrl+C to give up)",
                     settings["repeat_seconds"])
            await engine.wait_idle()
            log.info("acknowledged - test finished")
    finally:
        listener.cancel()
        # Close the fake event so the DB doesn't show it as still in stock.
        await engine.handle_reading(dataclasses.replace(reading, state=StockState.OUT_OF_STOCK))


def main() -> int:
    parser = argparse.ArgumentParser(prog="shelf_scout")
    sub = parser.add_subparsers(dest="command")
    test = sub.add_parser("test", help="fire a fake restock through every enabled channel")
    test.add_argument("--quiet", action="store_true", help="fake an over-cap price (one low-priority message)")
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
        asyncio.run(run_test(settings, args.quiet) if args.command == "test" else run(settings))
    except KeyboardInterrupt:
        log.info("stopped (Ctrl+C)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
