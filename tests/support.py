"""Testfixtures zonder shops.json, Google credentials of productieverbinding."""

from unittest.mock import mock_open, patch

# shops.py leest configuratie bij import; tests gebruiken uitsluitend hun eigen shop.
with patch("pathlib.Path.exists", return_value=True), patch(
    "pathlib.Path.open", mock_open(read_data="[]")
):
    from config.shops import Shop

import requests

BASE = "https://shop.example"
ROOT = BASE + "/sitemap.xml"
PRODUCTS = BASE + "/sitemap-products.xml"
PAGES = BASE + "/sitemap-pages.xml"
SHOP = Shop("test", "Test shop", BASE, BASE + "/", "nl-NL")


def xml(kind, locations):
    entry = "sitemap" if kind == "sitemapindex" else "url"
    entries = "".join(f"<{entry}><loc>{loc}</loc></{entry}>" for loc in locations)
    return f'<{kind} xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{entries}</{kind}>'


def response(body="", status=200):
    result = requests.Response()
    result.status_code = status
    result._content = body.encode()
    return result


def install_responses(collector, responses):
    def get(url, **kwargs):
        result = responses[url]
        if isinstance(result, Exception):
            raise result
        return result
    collector.session.get = get
