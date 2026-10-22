"""Tracker layer: free RSS/Atom feeds watched as an independent stock signal.

Why: it keeps working when a retailer blocks us. The cost is trust: a feed item says "PS5 Pro restock" but
carries no verified price or seller, so a hit becomes a loud alert labelled "unverified (tracker)".

Each feed in settings.json `feeds` gets its own poller (own interval, back-off and `health` row, named after
the feed), so a dead feed shows as an error there, never as "no stock". Two roles:
  "alert" (default): items that mention a PS5 Pro AND a restock word become an in-stock Reading.
  "news": PS5 items are saved to `announcements` for the dashboard (and optionally a heads-up message).

ponytail: RSS/Atom plus Telegram channel pages (t.me/s/<name>, no login, public channels only). Trackalacker (named in the PRD) has no feed and renders its listings with
JavaScript, so use its own email/text alerts instead. Add an "html" type when a source needs it.
"""
import html
import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from ..models import Layer, Reading, StockState
from ..pollers import ParseError, Poller

log = logging.getLogger("shelf_scout.feeds")

PS5_PRO = re.compile(r"(playstation\s*5|ps5)\s*pro", re.I)
PS5_ANY = re.compile(r"playstation\s*5|ps5", re.I)
RESTOCK = re.compile(r"restock|in[- ]stock|available|\blive\b", re.I)
HIT_TTL = 30 * 60  # a tracker hit counts as "in stock" this long, then the event closes so the next hit re-alerts
LABEL = "unverified (tracker)"
ATOM = "{http://www.w3.org/2005/Atom}"


@dataclass
class Item:
    title: str
    link: str
    published: float | None   # unix time, None if the feed gave no usable date


def _when(text: str | None) -> float | None:
    if not text:
        return None
    try:
        return parsedate_to_datetime(text).timestamp()  # RSS: "Tue, 20 Oct 2026 16:04:00 +0000"
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(text).astimezone(timezone.utc).timestamp()  # Atom: "2026-10-22T13:09:16+00:00"
    except ValueError:
        return None


def parse_feed(text: str) -> list[Item]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        raise ParseError("the feed isn't valid RSS/Atom XML (the link may be wrong, or the site served a web page). "
                         "Open the URL in a browser to check it") from None
    if root.tag == ATOM + "feed":
        entries = root.findall(ATOM + "entry")
        return [Item((e.findtext(ATOM + "title") or "").strip(), (e.find(ATOM + "link").get("href", "") if e.find(ATOM + "link") is not None else ""),
                     _when(e.findtext(ATOM + "published") or e.findtext(ATOM + "updated"))) for e in entries]
    if root.tag == "rss":
        return [Item((i.findtext("title") or "").strip(), (i.findtext("link") or "").strip(), _when(i.findtext("pubDate")))
                for i in root.iter("item")]
    raise ParseError(f"the feed's top-level tag is <{root.tag}>, not RSS or Atom. Check the URL in settings.json")


def parse_telegram(text: str) -> list[Item]:
    """A public channel's web view (https://t.me/s/<channel>) as feed items: one per message, link = the post."""
    out = []
    for block in text.split('data-post="')[1:]:
        post = block.split('"', 1)[0]
        body = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', block, re.S)
        when = re.search(r'<time datetime="([^"]+)"', block)
        if body:
            title = html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<br\s*/?>", " ", body.group(1))))
            out.append(Item(" ".join(title.split()), f"https://t.me/{post}", _when(when and when.group(1))))
    if not out and "tgme_page" not in text and "tgme_widget" not in text:
        raise ParseError("not a Telegram channel page. Use the https://t.me/s/<channel> form of the link (public channels only)")
    return out


class FeedPoller(Poller):
    layer = Layer.TRACKER
    empty_ok = True   # "nothing new" is the normal state of a feed, not a failure

    def __init__(self, client, get_settings, feed: dict, conn=None, notice=None):
        super().__init__(client, get_settings)
        self.feed, self.conn, self.notice = feed, conn, notice
        self.retailer = feed["name"]
        self.seen: set[str] = set()
        self.live: dict[str, float] = {}   # link -> when its in-stock reading was sent
        self.first = True

    @property
    def cfg(self) -> dict:
        """The feed's current settings, found by name so dashboard edits apply live. Deleted = idle."""
        for f in self.get_settings()["feeds"]:
            if f["name"] == self.retailer:
                return f
        return {**self.feed, "enabled": False}

    async def check(self) -> list[Reading]:
        parse = parse_telegram if self.cfg["type"] == "telegram" else parse_feed
        items = parse((await self.get(self.cfg["url"])).text)
        now = time.time()
        new = [i for i in items if i.link and i.link not in self.seen]
        self.seen.update(i.link for i in new)
        first, self.first = self.first, False
        if self.cfg["role"] == "news":
            await self.save_news(new, now, first)
            return []
        out = []
        for i in new:
            if not (PS5_PRO.search(i.title) and RESTOCK.search(i.title)):
                continue
            # Dated items count if recent; undated ones only if they showed up after startup.
            if (i.published is not None and now - i.published <= HIT_TTL) or (i.published is None and not first):
                self.live[i.link] = now
                log.info("%s: tracker hit: %s", self.retailer, i.title)
                out.append(Reading(self.retailer, StockState.IN_STOCK, Layer.TRACKER, i.link, None, LABEL, None, i.title[:140], now))
        for link, t in list(self.live.items()):
            if now - t > HIT_TTL:
                del self.live[link]
                out.append(Reading(self.retailer, StockState.OUT_OF_STOCK, Layer.TRACKER, link, None, None, None, None, now))
        return out

    async def save_news(self, new: list[Item], now: float, first: bool) -> None:
        for i in new:
            if not PS5_ANY.search(i.title):
                continue
            with self.conn:
                added = self.conn.execute("INSERT OR IGNORE INTO announcements (source,title,url,published) VALUES (?,?,?,?)",
                                          (self.retailer, i.title, i.link, i.published or now)).rowcount
            if added and not first and self.get_settings()["announcement_heads_up"] and self.notice:
                await self.notice(f"PlayStation news: {self.retailer}", i.title, i.link)


def build_feed_pollers(client, get_settings, conn, notice) -> list[FeedPoller]:
    return [FeedPoller(client, get_settings, f, conn, notice) for f in get_settings()["feeds"]]
