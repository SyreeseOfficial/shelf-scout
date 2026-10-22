"""`python -m shelf_scout` starts the service."""
import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import config, db

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
    # Later phases start pollers, the alert engine and the dashboard here.
    await asyncio.Event().wait()


def main() -> int:
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
        asyncio.run(run(settings))
    except KeyboardInterrupt:
        log.info("stopped (Ctrl+C)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
