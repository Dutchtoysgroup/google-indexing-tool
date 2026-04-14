"""Google Indexing API wrapper - pusht URLs voor indexering."""

from __future__ import annotations

import base64
import json
import logging
import time

import google.auth.transport.requests
import requests
from google.oauth2 import service_account

from config.settings import (
    GOOGLE_SERVICE_ACCOUNT_KEY,
    INDEXING_DAILY_LIMIT,
    INDEXING_DELAY_SECONDS,
    SERVICE_ACCOUNT_KEY_PATH,
)
from db.queries import mark_as_pushed, get_daily_api_usage, log_api_usage

logger = logging.getLogger(__name__)

INDEXING_ENDPOINT = "https://indexing.googleapis.com/v3/urlNotifications:publish"
SCOPES = ["https://www.googleapis.com/auth/indexing"]


class IndexingPusher:
    """Pusht niet-geIndexeerde URLs naar Google via de Indexing API."""

    def __init__(self):
        self.credentials = self._get_credentials()
        self._refresh_token()

    def _get_credentials(self) -> service_account.Credentials:
        """Laad Service Account credentials met indexing scope."""
        if GOOGLE_SERVICE_ACCOUNT_KEY and not SERVICE_ACCOUNT_KEY_PATH.exists():
            try:
                key_json = base64.b64decode(GOOGLE_SERVICE_ACCOUNT_KEY)
                key_data = json.loads(key_json)
                return service_account.Credentials.from_service_account_info(
                    key_data, scopes=SCOPES
                )
            except Exception:
                pass

        if SERVICE_ACCOUNT_KEY_PATH.exists():
            return service_account.Credentials.from_service_account_file(
                str(SERVICE_ACCOUNT_KEY_PATH), scopes=SCOPES
            )

        raise RuntimeError(
            "Geen Google Service Account credentials gevonden. "
            "Zet GOOGLE_SERVICE_ACCOUNT_KEY env var of plaats service-account-key.json"
        )

    def _refresh_token(self):
        self.credentials.refresh(google.auth.transport.requests.Request())

    def push_url(self, url: str) -> bool:
        """Push een enkele URL naar de Indexing API.

        Returns:
            True bij succes, False bij fout.
        """
        if not self.credentials.valid:
            self._refresh_token()

        try:
            resp = requests.post(
                INDEXING_ENDPOINT,
                headers={"Authorization": f"Bearer {self.credentials.token}"},
                json={
                    "url": url,
                    "type": "URL_UPDATED",
                },
                timeout=30,
            )

            if resp.status_code == 200:
                return True

            # Log specifieke fouten
            error_data = resp.json() if resp.text else {}
            error_msg = error_data.get("error", {}).get("message", resp.text)
            logger.warning(f"Indexing API fout voor {url}: {resp.status_code} - {error_msg}")
            return False

        except requests.RequestException as e:
            logger.error(f"Request fout bij pushen van {url}: {e}")
            return False

    def push_batch(self, urls: list[dict]) -> int:
        """Push een batch niet-geIndexeerde URLs.

        Args:
            urls: Lijst van dicts met 'shop_id' en 'url' keys

        Returns:
            Aantal succesvol gepushte URLs
        """
        # Check dagelijks limiet
        used_today = get_daily_api_usage("indexing")
        remaining = INDEXING_DAILY_LIMIT - used_today
        if remaining <= 0:
            logger.warning(f"Dagelijks push limiet bereikt ({used_today}/{INDEXING_DAILY_LIMIT})")
            return 0

        to_push = urls[:remaining]
        success_count = 0

        for url_row in to_push:
            url = url_row["url"]
            shop_id = url_row["shop_id"]

            if self.push_url(url):
                mark_as_pushed(shop_id, url)
                success_count += 1
                logger.info(f"  [PUSHED] {url}")
            else:
                logger.warning(f"  [FAILED] {url}")

            time.sleep(INDEXING_DELAY_SECONDS)

        # Log API usage per shop
        shop_counts: dict[str, int] = {}
        for url_row in to_push[:success_count]:
            sid = url_row["shop_id"]
            shop_counts[sid] = shop_counts.get(sid, 0) + 1
        for sid, count in shop_counts.items():
            log_api_usage(sid, "indexing", count)

        return success_count
