"""Sitemap collector - haalt URLs op uit alle shop sitemaps."""

from __future__ import annotations

import logging
import re

import requests
from bs4 import BeautifulSoup

from config.shops import Shop
from db.queries import upsert_urls_batch, mark_missing_urls

logger = logging.getLogger(__name__)

# Sitemap bestandsnaam -> url_type mapping
TYPE_PATTERNS = {
    r"product": "product",
    r"collection": "collection",
    r"page": "page",
    r"blog": "blog",
    r"faq": "faq",
    r"article": "blog",
}

HEADERS = {
    "User-Agent": "EXIT-Indexing-Tool/1.0",
}


class SitemapCollector:
    """Verzamelt URLs uit sitemaps van een webshop."""

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def collect(self, shop: Shop) -> dict[str, list[str]]:
        """Haal alle URLs op uit de sitemaps van een shop.

        Returns:
            Dict met url_type -> [urls]
        """
        logger.info(f"Scanning sitemaps voor {shop.name} ({shop.base_url})")

        # Stap 1: Haal sitemap index op
        sitemap_urls = self._get_sitemap_index(shop.base_url)
        if not sitemap_urls:
            # Probeer directe sitemap URL
            sitemap_urls = [f"{shop.base_url}/sitemap.xml"]
            logger.info("Geen sitemap index gevonden, probeer directe sitemap")

        # Stap 2: Parse alle child sitemaps
        all_urls: dict[str, list[str]] = {}
        all_url_pairs: list[tuple[str, str | None]] = []

        for sitemap_url in sitemap_urls:
            url_type = self._detect_type(sitemap_url)
            urls = self._parse_sitemap(sitemap_url, shop.base_url)
            if urls:
                all_urls.setdefault(url_type or "other", []).extend(urls)
                all_url_pairs.extend([(url, url_type) for url in urls])
                logger.info(f"  {sitemap_url}: {len(urls)} URLs (type: {url_type or 'other'})")

        # Stap 3: Batch upsert in database
        if all_url_pairs:
            upsert_urls_batch(shop.shop_id, all_url_pairs)

        # Stap 4: Markeer verdwenen URLs
        current_urls = {url for url, _ in all_url_pairs}
        mark_missing_urls(shop.shop_id, current_urls)

        total = sum(len(v) for v in all_urls.values())
        logger.info(f"  Totaal: {total} URLs voor {shop.name}")

        return all_urls

    def _get_sitemap_index(self, base_url: str) -> list[str]:
        """Haal de sitemap index op en retourneer child sitemap URLs."""
        index_url = f"{base_url}/sitemap.xml"
        try:
            resp = self.session.get(index_url, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Fout bij ophalen sitemap index {index_url}: {e}")
            return []

        soup = BeautifulSoup(resp.text, "lxml-xml")
        sitemaps = []
        for sitemap in soup.find_all("sitemap"):
            loc = sitemap.find("loc")
            if loc and loc.text:
                sitemaps.append(loc.text.strip())

        if sitemaps:
            logger.info(f"  Sitemap index: {len(sitemaps)} child sitemaps gevonden")
        return sitemaps

    def _parse_sitemap(self, sitemap_url: str, base_url: str) -> list[str]:
        """Parse een enkele sitemap en retourneer URLs."""
        try:
            resp = self.session.get(sitemap_url, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Fout bij ophalen sitemap {sitemap_url}: {e}")
            return []

        soup = BeautifulSoup(resp.text, "lxml-xml")

        # Check of dit ook een sitemap index is (geneste indexes)
        nested_sitemaps = soup.find_all("sitemap")
        if nested_sitemaps:
            urls = []
            for sm in nested_sitemaps:
                loc = sm.find("loc")
                if loc and loc.text:
                    urls.extend(self._parse_sitemap(loc.text.strip(), base_url))
            return urls

        # Parse URL entries
        urls = []
        for loc in soup.find_all("loc"):
            url = loc.text.strip()
            if url.startswith(base_url):
                urls.append(url)

        return list(set(urls))

    def _detect_type(self, sitemap_url: str) -> str | None:
        """Detecteer het URL type op basis van de sitemap bestandsnaam."""
        lower = sitemap_url.lower()
        for pattern, url_type in TYPE_PATTERNS.items():
            if re.search(pattern, lower):
                return url_type
        return None
