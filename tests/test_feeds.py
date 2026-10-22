"""Tracker feeds + events. Fixtures: tests/fixtures/feeds/*.xml are real feed captures trimmed to two items;
the restock items used below are built from them in code."""
import asyncio
import time
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path

import httpx
import pytest

from shelf_scout import config, db
from shelf_scout.engine import Engine
from shelf_scout.pollers import ParseError, RunState, poll_step
from shelf_scout.trackers import events, feeds

FIX = Path(__file__).parent / "fixtures" / "feeds"


def rss(*items: tuple[str, str, float | None]) -> str:
    """(title, link, unix time or None) -> a minimal RSS feed."""
    body = "".join(f"<item><title>{t}</title><link>{l}</link>"
                   + (f"<pubDate>{format_datetime(datetime.fromtimestamp(p, timezone.utc))}</pubDate>" if p else "") + "</item>"
                   for t, l, p in items)
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>{body}</channel></rss>'


class Recorder:
    name = "rec"

    def __init__(self):
        self.alerts = []

    async def send(self, alert):
        self.alerts.append(alert)


def make(tmp_path, bodies, role="alert", **settings):
    """A FeedPoller whose HTTP replies are the queued `bodies` (str = 200 body, int = that status code)."""
    queue = list(bodies)

    def handler(request):
        b = queue.pop(0)
        return httpx.Response(b, text="no") if isinstance(b, int) else httpx.Response(200, text=b, headers={"content-type": "application/xml"})

    feed = {"name": "TestFeed", "url": "https://feeds.example.com/x.rss", "type": "rss", "role": role, "interval_seconds": 60}
    s = config.validate({"feeds": [feed], **settings})
    conn = db.connect(tmp_path / "t.db")
    rec = Recorder()
    engine = Engine(s, conn, [rec])
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return feeds.FeedPoller(client, lambda: engine.settings, s["feeds"][0], conn, engine.notice), engine, conn, rec


def step(poller, engine, conn, st):
    return asyncio.run(poll_step(poller, engine, conn, st))


# ---- parsing --------------------------------------------------------------------------------

def test_parse_real_atom_and_rss_captures():
    atom = feeds.parse_feed((FIX / "reddit_atom.xml").read_text())
    assert len(atom) == 2 and atom[0].link.startswith("https://www.reddit.com/") and atom[0].published
    for name in ("slickdeals_rss.xml", "psblog_rss.xml"):
        items = feeds.parse_feed((FIX / name).read_text())
        assert len(items) == 2 and all(i.title and i.link and i.published for i in items)


def test_garbage_is_parse_error():
    for bad in ((FIX / "garbage.html").read_text(), "", "<html><body/></html>"):
        with pytest.raises(ParseError):
            feeds.parse_feed(bad)


# ---- alert feeds ----------------------------------------------------------------------------

def test_tracker_hit_alone_makes_a_full_loud_alert(tmp_path):
    now = time.time()
    poller, engine, conn, rec = make(tmp_path, [rss(("PS5 Pro restock live at Target!", "https://x.example/1", now - 60))])
    step(poller, engine, conn, RunState())
    [alert] = rec.alerts
    [row] = alert.rows
    assert alert.loud and row.layer.value == "tracker" and row.seller == feeds.LABEL and row.url == "https://x.example/1"
    assert row.price_cents is None  # unverified: no price, still loud
    assert conn.execute("SELECT retailer FROM events").fetchone()["retailer"] == "TestFeed"


def test_irrelevant_old_and_duplicate_items_do_not_alert(tmp_path):
    now = time.time()
    poller, engine, conn, rec = make(tmp_path, [
        rss(("PS5 Pro restock at Target", "https://x/old", now - 3 * 3600),   # hours old
            ("PS5 restock at Target", "https://x/slim", now - 30),            # not a Pro
            ("PS5 Pro price drop analysis", "https://x/nokw", now - 30)),     # no restock word
        rss(("PS5 Pro restock at Target", "https://x/old", now - 3 * 3600)),
    ])
    st = RunState()
    step(poller, engine, conn, st)
    step(poller, engine, conn, st)
    assert rec.alerts == []


def test_hit_closes_after_ttl_so_the_next_hit_alerts_again(tmp_path):
    now = time.time()
    poller, engine, conn, rec = make(tmp_path, [rss(("PS5 Pro in stock", "https://x/a", now - 10)), rss(), rss(("PS5 Pro in stock", "https://x/b", now))])
    st = RunState()
    step(poller, engine, conn, st)
    poller.live["https://x/a"] -= feeds.HIT_TTL + 1   # pretend 30 minutes passed
    step(poller, engine, conn, st)
    assert conn.execute("SELECT ended FROM events").fetchone()["ended"] is not None
    step(poller, engine, conn, st)
    assert len(rec.alerts) == 2


def test_empty_feed_is_healthy_but_failure_is_an_error_not_no_stock(tmp_path):
    poller, engine, conn, rec = make(tmp_path, [rss(), 500, 429])
    st = RunState()
    step(poller, engine, conn, st)
    assert conn.execute("SELECT state FROM health").fetchone()["state"] == "ok"
    step(poller, engine, conn, st)
    row = conn.execute("SELECT * FROM health").fetchone()
    assert row["state"] == "error" and row["error_count"] == 1 and "500" in row["note"]
    step(poller, engine, conn, st)  # a block: backs off and sends the one notice
    assert conn.execute("SELECT state FROM health").fetchone()["state"] == "blocked" and len(rec.alerts) == 1
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0  # never read as stock or as sold out


# ---- news feeds + calendar ------------------------------------------------------------------

def test_news_feed_saves_ps5_items_and_optional_heads_up(tmp_path):
    now = time.time()
    first = rss(("Old PS5 news", "https://n/0", now - 100))
    second = rss(("Old PS5 news", "https://n/0", now - 100), ("PS5 Pro price change", "https://n/1", now - 5), ("Wolverine guide", "https://n/2", now - 5))
    poller, engine, conn, rec = make(tmp_path, [first, second], role="news", announcement_heads_up=True)
    st = RunState()
    step(poller, engine, conn, st)
    step(poller, engine, conn, st)
    assert [r["title"] for r in conn.execute("SELECT title FROM announcements ORDER BY id")] == ["Old PS5 news", "PS5 Pro price change"]
    assert len(rec.alerts) == 1 and rec.alerts[0].notice.startswith("PlayStation news")  # only the new one; not the first-poll backlog


def test_upcoming_is_sorted_and_merges_calendar_and_news(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    now = datetime(2026, 11, 28, 12).timestamp()
    conn.execute("INSERT INTO announcements (source,title,url,published) VALUES ('Blog','Recent PS5 news','https://n',?)", (now - 86400,))
    conn.execute("INSERT INTO announcements (source,title,url,published) VALUES ('Blog','Stale PS5 news','https://n2',?)", (now - 30 * 86400,))
    items = events.upcoming(conn, now)
    assert [i["when"] for i in items] == sorted(i["when"] for i in items)
    titles = [i["title"] for i in items]
    assert titles[:3] == ["Recent PS5 news", "Cyber Monday", "Green Monday"]  # Black Friday already passed; stale news dropped
    assert "Stale PS5 news" not in titles


# ---- settings -------------------------------------------------------------------------------

def test_feed_settings_validation_names_the_bad_key():
    ok = config.validate({"feeds": [{"name": "A", "url": "https://a.example/rss"}]})["feeds"][0]
    assert (ok["type"], ok["role"], ok["interval_seconds"]) == ("rss", "alert", 60)
    for bad, key in (({"name": "A", "url": "ftp://x"}, "feeds[0].url"), ({"name": "A", "url": "https://a", "type": "html"}, "feeds[0].type"),
                     ({"name": "A", "url": "https://a", "role": "x"}, "feeds[0].role"), ({"url": "https://a"}, "feeds[0].name"),
                     ({"name": "A", "url": "https://a", "interval_seconds": 1}, "feeds[0].interval_seconds")):
        with pytest.raises(config.ConfigError, match=key.replace("[", r"\[").replace("]", r"\]")):
            config.validate({"feeds": [bad]})
    with pytest.raises(config.ConfigError, match="unique"):
        config.validate({"feeds": [{"name": "A", "url": "https://a"}, {"name": "A", "url": "https://b"}]})


def test_parse_telegram_real_capture():
    items = feeds.parse_telegram((FIX / "telegram_channel.html").read_text())
    assert len(items) == 2 and items[0].link.startswith("https://t.me/durov/")
    assert items[0].title and "<" not in items[0].title and items[0].published


def test_parse_telegram_restock_post_and_wrong_page():
    page = ('<div class="tgme_widget_message" data-post="chan/7"><div class="tgme_widget_message_text js-message_text">'
            'PS5 Pro <b>restock</b> at Target<br/>&amp; Walmart</div><time datetime="2026-10-22T13:09:16+00:00"></time></div>')
    (item,) = feeds.parse_telegram(page)
    assert item.title == "PS5 Pro restock at Target & Walmart" and item.link == "https://t.me/chan/7"
    assert feeds.PS5_PRO.search(item.title) and feeds.RESTOCK.search(item.title)
    with pytest.raises(ParseError):
        feeds.parse_telegram("<html>hello</html>")


def test_rss_item_without_title_uses_description():
    xml = ("<rss><channel><item><link>https://bsky.app/p/1</link><description>PS5 Pro back in stock at Walmart\n\n#ad</description>"
           "<pubDate>22 Oct 2026 22:16 +0000</pubDate></item></channel></rss>")
    [i] = feeds.parse_feed(xml)
    assert i.title == "PS5 Pro back in stock at Walmart #ad" and i.published is not None
