"""Explicit opt-in for Google's narrowly scoped Indexing API."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from config.settings import PROJECT_DIR

ELIGIBLE_PAGES_FILE = PROJECT_DIR / "config" / "indexing-pages.json"
SUPPORTED_PAGE_TYPES = frozenset({"JobPosting", "BroadcastEvent"})


def get_eligible_pages() -> dict[str, str]:
    """An absent/empty allowlist disables notifications for all webshop URLs.

    Types must be editorially verified; the pusher also checks current JSON-LD.
    Sitemap filenames and a failed inspection never establish eligibility.
    """
    config_file = Path(os.environ.get("INDEXING_PAGES_FILE", ELIGIBLE_PAGES_FILE))
    if not config_file.exists():
        return {}
    data = json.loads(config_file.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("indexing-pages.json must map exact URLs to supported page types")
    for url, page_type in data.items():
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or not parsed.netloc or parsed.username
                or parsed.password or parsed.fragment or page_type not in SUPPORTED_PAGE_TYPES):
            raise ValueError(f"Unsupported Indexing API configuration for {url}")
    return data
