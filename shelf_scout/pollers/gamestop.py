"""GameStop: product page (schema.org JSON-LD, see jsonld.py). Page layer only.

STATUS: gamestop.com answers an honest, non-browser client with HTTP 403 (a Cloudflare-style bot check), so
live reads fail with a "blocked" error. We don't get around that. The parser is checked on hand-written
fixtures only. Put the full product link in retailers.gamestop.urls (GameStop ids don't map to a link on
their own). Note GameStop redirects unknown ids to a random product: the parser refuses anything that isn't a PS5 Pro.
"""
from .jsonld import JsonLdPoller


class GameStop(JsonLdPoller):
    retailer, label = "gamestop", "GameStop"


POLLER = GameStop
