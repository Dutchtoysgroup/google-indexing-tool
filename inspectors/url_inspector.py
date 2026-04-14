"""URL Inspection API wrapper."""

from __future__ import annotations

import base64
import json
import logging
import tempfile
import time

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

logger = logging.getLogger(__name__)

INSPECTION_ENDPOINT = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]


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
            logger.error(f"API fout bij inspectie van {url}: {e}")
            return None

        # Parse het resultaat
        inspection = data.get("inspectionResult", {})
        index_status = inspection.get("indexStatusResult", {})

        result = {
            "coverage_state": index_status.get("coverageState"),
            "verdict": index_status.get("verdict"),
            "robots_txt_state": index_status.get("robotsTxtState"),
            "indexing_state": index_status.get("indexingState"),
            "last_crawl_time": index_status.get("lastCrawlTime"),
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
        # Check dagelijks limiet
        used_today = get_daily_api_usage("inspection", shop_id)
        remaining = INSPECTION_DAILY_LIMIT_PER_SHOP - used_today
        if remaining <= 0:
            logger.warning(f"Dagelijks limiet bereikt voor {shop_id} ({used_today} inspections)")
            return 0

        to_inspect = urls[:remaining]
        success_count = 0

        for url_row in to_inspect:
            url = url_row["url"]
            result = self.inspect_url(url, site_url, language_code)
            if result:
                update_inspection_result(shop_id, url, result)
                success_count += 1
                verdict = result.get("verdict", "?")
                state = result.get("coverage_state", "?")
                logger.info(f"  [{verdict}] {url} - {state}")
            else:
                logger.warning(f"  [FOUT] {url}")

            time.sleep(INSPECTION_DELAY_SECONDS)

        # Log API usage
        if success_count > 0:
            log_api_usage(shop_id, "inspection", success_count)

        return success_count
