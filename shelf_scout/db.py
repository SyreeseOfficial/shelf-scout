"""SQLite storage: history, health and events. Tables are created if missing."""
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (          -- latest reading per listing
    retailer TEXT NOT NULL, url TEXT NOT NULL, layer TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL, price_cents INTEGER, seller TEXT, fulfillment TEXT, at REAL NOT NULL,
    PRIMARY KEY (retailer, url, layer, detail)
);
CREATE TABLE IF NOT EXISTS events (            -- one row per restock (out -> in)
    id INTEGER PRIMARY KEY AUTOINCREMENT, retailer TEXT NOT NULL, started REAL NOT NULL,
    ended REAL, price_cents INTEGER, seller TEXT, acked_at REAL
);
CREATE TABLE IF NOT EXISTS health (            -- one row per retailer/tracker
    retailer TEXT PRIMARY KEY, last_ok REAL, error_count INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL DEFAULT 'unknown', note TEXT
);
CREATE TABLE IF NOT EXISTS announcements (
    id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, title TEXT NOT NULL,
    url TEXT, published REAL, UNIQUE (source, title)
);
"""


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
