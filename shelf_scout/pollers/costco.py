"""Costco: product page (schema.org JSON-LD, see jsonld.py). Page layer only.

STATUS: costco.com serves its pages to an honest client, but I couldn't find a live PS5 Pro product link
(Costco only lists the console in short-lived bundles), so the parser is checked on hand-written fixtures
only. When Costco lists one, put its full link in retailers.costco.urls. Costco prices can be member-only:
the price shown may be the member price.
"""
from .jsonld import JsonLdPoller


class Costco(JsonLdPoller):
    retailer, label = "costco", "Costco"


POLLER = Costco
