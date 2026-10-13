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
from db.queries import (
    reserve_indexing_request,
    complete_indexing_request,
)

logger = logging.getLogger(__name__)

INDEXING_ENDPOINT = "https://indexing.googleapis.com/v3/urlNotifications:publish"
SCOPES = ["https://www.googleapis.com/auth/indexing"]


class IndexingQuotaExceeded(Exception):
    """Geen budgetplek beschikbaar; er is geen HTTP-request verstuurd."""


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

    def push_url(
        self, url: str, shop_id: str | None, priority_id: int | None = None,
    ) -> bool:
        """Reserveer budget, verstuur één request en registreer de uitkomst."""
        if not self.credentials.valid:
            self._refresh_token()

        request_id = reserve_indexing_request(
            shop_id, url, INDEXING_DAILY_LIMIT, priority_id=priority_id,
        )
        if request_id is None:
            raise IndexingQuotaExceeded

        # Alleen netwerkfouten afvangen. Bij een crash of databasefout blijft de
        # reeds gecommitte reservering bestaan en wordt geen succes verzonnen.
        try:
            resp = requests.post(
                INDEXING_ENDPOINT,
                headers={"Authorization": f"Bearer {self.credentials.token}"},
                json={"url": url, "type": "URL_UPDATED"},
                timeout=30,
            )
        except requests.RequestException as exc:
            error = str(exc)[:2000]
            complete_indexing_request(request_id, "unknown", error=error)
            logger.error("Onbekende requestuitkomst voor %s: %s", url, error)
            return False

        success = resp.status_code == 200
        error = None if success else resp.text[:2000] or f"HTTP {resp.status_code}"
        complete_indexing_request(
            request_id, "succeeded" if success else "failed",
            http_status=resp.status_code, error=error,
        )
        if not success:
            logger.warning("Indexing API fout voor %s: %s - %s", url, resp.status_code, error)
        return success

    def push_priority_batch(self, priority_rows: list[dict]) -> int:
        """Push priority URLs met hetzelfde duurzame quotum als reguliere URLs."""
        return self._push_batch(priority_rows, priority=True)

    def push_batch(self, urls: list[dict]) -> int:
        """Push URLs; tel alleen daadwerkelijk geregistreerde successen."""
        return self._push_batch(urls, priority=False)

    def _push_batch(self, rows: list[dict], *, priority: bool) -> int:
        success_count = 0
        for row in rows:
            try:
                ok = self.push_url(
                    row["url"], row.get("shop_id"),
                    priority_id=row["id"] if priority else None,
                )
            except IndexingQuotaExceeded:
                logger.warning("Dagelijks pushquotum bereikt (%s)", INDEXING_DAILY_LIMIT)
                break
            if ok:
                success_count += 1
                logger.info("  [PUSHED]%s %s", "[priority]" if priority else "", row["url"])
            else:
                logger.warning("  [NOT PUSHED]%s %s", "[priority]" if priority else "", row["url"])
            time.sleep(INDEXING_DELAY_SECONDS)
        return success_count
