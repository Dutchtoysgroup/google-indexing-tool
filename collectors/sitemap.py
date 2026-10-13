"""Sitemap collector - haalt URLs op uit alle shop sitemaps."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse
from xml.etree import ElementTree

import requests

from config.shops import Shop
from db.queries import apply_sitemap_snapshot

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
    "User-Agent": "GoogleIndexingTool/1.0 (+https://github.com/your-org/google-indexing-tool)",
}


@dataclass
class SitemapResult:
    """URLs plus volledigheid van de volledige (eventueel geneste) sitemapboom."""

    urls: dict[str, list[str]] = field(default_factory=dict)
    failed_sitemaps: list[str] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.failed_sitemaps

    @property
    def total(self) -> int:
        return sum(len(urls) for urls in self.urls.values())


class SitemapCollector:
    """Verzamelt URLs; publiceert uitsluitend volledige snapshots."""

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def collect(self, shop: Shop) -> SitemapResult:
        logger.info(f"Scanning sitemaps voor {shop.name} ({shop.base_url})")
        result = self._parse_sitemap(
            f"{shop.base_url.rstrip('/')}/sitemap.xml", shop.base_url
        )
        pairs = [
            (url, None if url_type == "other" else url_type)
            for url_type, urls in result.urls.items()
            for url in urls
        ]
        apply_sitemap_snapshot(shop.shop_id, pairs, complete=result.complete)
        if result.complete:
            logger.info(f"  Volledig: {result.total} URLs voor {shop.name}")
        else:
            logger.warning(
                "Sitemapscan incompleet voor %s: %s; %s URLs verzameld, "
                "bestaande URLs ongewijzigd, verwijderdetectie overgeslagen",
                shop.name, ", ".join(result.failed_sitemaps), result.total,
            )
        return result

    def _parse_sitemap(
        self, sitemap_url: str, base_url: str,
        ancestors: frozenset[str] = frozenset(),
        inherited_type: str | None = None,
    ) -> SitemapResult:
        """Lees strikt XML en draag fouten uit elke child naar de root mee."""
        result = SitemapResult()

        def fail(reason: str) -> SitemapResult:
            logger.error("Onvolledige sitemap %s: %s", sitemap_url, reason)
            result.failed_sitemaps.append(sitemap_url)
            result.errors.append({"url": sitemap_url, "error": reason})
            return result

        if sitemap_url in ancestors:
            return fail("cyclische sitemapindex")
        if len(ancestors) >= 50:
            return fail("maximale sitemapdiepte bereikt")
        try:
            resp = self.session.get(sitemap_url, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as exc:
            return fail(str(exc))

        try:
            root = ElementTree.fromstring(resp.content)
        except ElementTree.ParseError as exc:
            return fail(f"ongeldige XML: {exc}")

        namespace = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
        prefix = namespace if root.tag.startswith(namespace) else ""
        is_index = root.tag == f"{prefix}sitemapindex"
        if not is_index and root.tag != f"{prefix}urlset":
            return fail("geen sitemapindex of urlset")

        entries = root.findall(f"{prefix}{'sitemap' if is_index else 'url'}")
        if not entries:
            return fail("lege sitemap")

        url_type = self._detect_type(sitemap_url) or inherited_type
        base = base_url.rstrip("/")
        for entry in entries:
            locations = entry.findall(f"{prefix}loc")
            location = (locations[0].text or "").strip() if len(locations) == 1 else ""
            parsed = urlparse(location)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                fail("ontbrekende of ongeldige loc")
                continue
            if is_index:
                child = self._parse_sitemap(
                    location, base_url, ancestors | {sitemap_url}, url_type
                )
                for child_type, urls in child.urls.items():
                    result.urls.setdefault(child_type, []).extend(urls)
                result.failed_sitemaps.extend(child.failed_sitemaps)
                result.errors.extend(child.errors)
            elif location == base or location.startswith(base + "/"):
                result.urls.setdefault(url_type or "other", []).append(location)

        if not result.urls and result.complete:
            fail("geen URLs voor deze shop")
        result.urls = {key: list(dict.fromkeys(urls)) for key, urls in result.urls.items()}
        result.failed_sitemaps = list(dict.fromkeys(result.failed_sitemaps))
        return result

    def _detect_type(self, sitemap_url: str) -> str | None:
        """Detecteer het URL type op basis van de sitemap bestandsnaam."""
        lower = sitemap_url.lower()
        for pattern, url_type in TYPE_PATTERNS.items():
            if re.search(pattern, lower):
                return url_type
        return None
