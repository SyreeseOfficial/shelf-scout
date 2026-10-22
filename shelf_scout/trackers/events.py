"""Sale calendar + announcements, merged into one date-sorted list for the dashboard.

The calendar is a small hand-kept JSON file next to this module (add next year's dates there).
Announcements are filled by `news` feeds (see feeds.py) and live in the `announcements` table.
"""
import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path

CALENDAR = Path(__file__).with_name("sale_calendar.json")
RECENT_DAYS = 7  # how far back announcements still show


def upcoming(conn, now: float | None = None, calendar: Path = CALENDAR) -> list[dict]:
    """Future sale days + announcements from the last week, oldest first.
    Each item: {"when": "YYYY-MM-DD", "kind": "sale" | "news", "title", "note", "url"}."""
    now = time.time() if now is None else now
    today = datetime.fromtimestamp(now).date()
    items = [{"when": e["date"], "kind": "sale", "title": e["title"], "note": e.get("note", ""), "url": None}
             for e in json.loads(calendar.read_text()) if date.fromisoformat(e["date"]) >= today]
    cutoff = (datetime.fromtimestamp(now) - timedelta(days=RECENT_DAYS)).timestamp()
    for r in conn.execute("SELECT source,title,url,published FROM announcements WHERE published >= ?", (cutoff,)):
        items.append({"when": datetime.fromtimestamp(r["published"]).date().isoformat(), "kind": "news",
                      "title": r["title"], "note": r["source"], "url": r["url"]})
    return sorted(items, key=lambda i: i["when"])


def is_sale_day(now: float | None = None, calendar: Path = CALENDAR) -> bool:
    """True if today (local) is a date in the sale calendar."""
    today = datetime.fromtimestamp(time.time() if now is None else now).date().isoformat()
    return any(e["date"] == today for e in json.loads(calendar.read_text()))
