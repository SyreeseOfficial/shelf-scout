"""Walmart: product page (schema.org JSON-LD, see jsonld.py). Page layer only.

STATUS: walmart.com redirects an honest, non-browser client to its /blocked page, so live reads fail with
a "blocked" error. We don't get around that. The parser is checked on hand-written fixtures only.
Marketplace sellers are labelled: the seller comes from the page's offer, "Walmart.com" for first-party.
Put the item id (the number at the end of /ip/<name>/<id>) in retailers.walmart.skus, or full links in urls.
"""
from .jsonld import JsonLdPoller


class Walmart(JsonLdPoller):
    retailer, label = "walmart", "Walmart"
    link_template = "https://www.walmart.com/ip/{sku}"


POLLER = Walmart
