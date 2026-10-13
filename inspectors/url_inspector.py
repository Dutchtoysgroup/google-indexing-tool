"""URL Inspection API wrapper."""

from __future__ import annotations

import base64
import json
import logging
import time
from dataclasses import dataclass, field

import google.auth.transport.requests
import requests
from google.oauth2 import service_account

from config.settings import (
    GOOGLE_SERVICE_ACCOUNT_KEY,
    INSPECTION_DELAY_SECONDS,
    INSPECTION_DAILY_LIMIT_PER_SHOP,
    SERVICE_ACCOUNT_KEY_PATH,
)
from db.queries import update_inspection_result, get_daily_api_usage, log_api_usage
from inspectors.diagnostics import diagnose
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

INSPECTION_ENDPOINT = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]


@dataclass
class InspectionBatchResult:
    selected: int
    attempted: int = 0
    succeeded: int = 0
    skipped: int = 0
    errors: list[dict] = field(default_factory=list)
    observations: list[dict] = field(default_factory=list)

    @property
    def status(self):
        if self.errors:
            return "incomplete" if self.succeeded else "failed"
        return "success"


class URLInspector:
    """Checkt de indexeringsstatus van URLs via de Google URL Inspection API."""

    def __init__(self):
        self.credentials = self._get_credentials()
        self._refresh_token()

    def _get_credentials(self) -> service_account.Credentials:
        """Laad Service Account credentials."""
        # Optie 1: Base64-encoded JSON in env var (GitHub Actions)
        if GOOGLE_SERVICE_ACCOUNT_KEY and not SERVICE_ACCOUNT_KEY_PATH.exists():
            try:
                key_json = base64.b64decode(GOOGLE_SERVICE_ACCOUNT_KEY)
                key_data = json.loads(key_json)
                return service_account.Credentials.from_service_account_info(
                    key_data, scopes=SCOPES
                )
            except Exception:
                pass

        # Optie 2: JSON bestand op disk (lokaal)
        if SERVICE_ACCOUNT_KEY_PATH.exists():
            return service_account.Credentials.from_service_account_file(
                str(SERVICE_ACCOUNT_KEY_PATH), scopes=SCOPES
            )

        raise RuntimeError(
            "Geen Google Service Account credentials gevonden. "
            "Zet GOOGLE_SERVICE_ACCOUNT_KEY env var of plaats service-account-key.json"
        )

    def _refresh_token(self):
        """Ververs het OAuth token."""
        self.credentials.refresh(google.auth.transport.requests.Request())

    def inspect_url(self, url: str, site_url: str, language_code: str) -> dict | None:
        """Inspecteer een enkele URL.

        Returns:
            Dict met inspection resultaat of None bij fout.
        """
        self.last_error = None
        # Token verversen als nodig
        if not self.credentials.valid:
            self._refresh_token()

        try:
            resp = requests.post(
                INSPECTION_ENDPOINT,
                headers={"Authorization": f"Bearer {self.credentials.token}"},
                json={
                    "inspectionUrl": url,
                    "siteUrl": site_url,
                    "languageCode": language_code,
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            self.last_error = f"{type(e).__name__}: {e}"
            logger.error(f"API fout bij inspectie van {url}: {e}")
            return None

        # Parse het resultaat
        inspection = data.get("inspectionResult", {})
        index_status = inspection.get("indexStatusResult", {})

        if not index_status.get("verdict"):
            self.last_error = "Invalid API response: missing indexStatusResult.verdict"
            logger.error(f"API fout bij inspectie van {url}: {self.last_error}")
            return None

        result = {
            "coverage_state": index_status.get("coverageState"),
            "verdict": index_status.get("verdict"),
            "robots_txt_state": index_status.get("robotsTxtState"),
            "indexing_state": index_status.get("indexingState"),
            "last_crawl_time": index_status.get("lastCrawlTime"),
            "google_canonical": index_status.get("googleCanonical"),
            "user_canonical": index_status.get("userCanonical"),
            "page_fetch_state": index_status.get("pageFetchState"),
            "sitemaps": index_status.get("sitemap", []),
        }

        return result

    def inspect_batch(
        self, shop_id: str, urls: list[dict], site_url: str, language_code: str
    ) -> int:
        """Inspecteer een batch URLs voor een shop.

        Args:
            shop_id: Shop identifier
            urls: Lijst van dicts met 'url' key
            site_url: GSC property URL
            language_code: Taalcode voor de API

        Returns:
            Aantal succesvol geInspecteerde URLs
        """
        return self.inspect_batch_result(shop_id, urls, site_url, language_code).succeeded

    def inspect_batch_result(
        self, shop_id: str, urls: list[dict], site_url: str, language_code: str
    ) -> InspectionBatchResult:
        """Return counts and URL-specific diagnostics, including swallowed API errors.

        Quota exclusions are expected scheduling, not API failures. The existing
        inspect_batch entry point keeps its integer return for callers.
        """
        batch = InspectionBatchResult(selected=len(urls))
        used_today = get_daily_api_usage("inspection", shop_id)
        remaining = max(0, INSPECTION_DAILY_LIMIT_PER_SHOP - used_today)
        batch.skipped = max(0, len(urls) - remaining)
        for url_row in urls[:remaining]:
            url = url_row["url"]
            batch.attempted += 1
            self.last_error = None
            try:
                result = self.inspect_url(url, site_url, language_code)
                if result:
                    update_inspection_result(shop_id, url, result)
                    batch.succeeded += 1
                    diagnosis = diagnose(url, result)
                    batch.observations.append({
                        "url": url, "url_type": url_row.get("url_type"),
                        "observed_at": datetime.now(timezone.utc).isoformat(),
                        **result, **diagnosis,
                    })
                    logger.info(f"  [OBSERVED] {url}: {diagnosis}")
                    logger.info(f"  [{result.get('verdict', '?')}] {url}")
                else:
                    batch.errors.append({"url": url, "error": self.last_error or "Inspection failed"})
            except Exception as exc:
                batch.errors.append({"url": url, "error": f"{type(exc).__name__}: {exc}"})
            time.sleep(INSPECTION_DELAY_SECONDS)

        if batch.succeeded:
            log_api_usage(shop_id, "inspection", batch.succeeded)
        for error in batch.errors:
            logger.error(f"  [{shop_id}] {error['url']}: {error['error']}")
        return batch
