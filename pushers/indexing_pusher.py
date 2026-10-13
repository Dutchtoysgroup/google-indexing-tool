"""Restricted Indexing API notifications; acceptance never means indexed."""

from __future__ import annotations

import base64
import json
import logging
import time

import google.auth.transport.requests
import requests
from google.oauth2 import service_account

from config.indexing_api import get_eligible_pages
from pushers.eligibility import verify_page_type
from config.settings import (
    GOOGLE_SERVICE_ACCOUNT_KEY,
    INDEXING_DAILY_LIMIT,
    INDEXING_DELAY_SECONDS,
    SERVICE_ACCOUNT_KEY_PATH,
)
from db.queries import (
    reserve_indexing_request,
    complete_indexing_request,
    mark_priority_not_supported,
)


logger = logging.getLogger(__name__)

INDEXING_ENDPOINT = "https://indexing.googleapis.com/v3/urlNotifications:publish"
SCOPES = ["https://www.googleapis.com/auth/indexing"]


class IndexingQuotaExceeded(Exception):
    """No durable quota reservation available; no request was sent."""


class IndexingPusher:
    """Notify only explicitly allowed, verified JobPosting/live video pages."""

    def __init__(self):
        self.credentials = None
        self.allowed_pages = get_eligible_pages()
        self.last_notification = {}
        self.last_batch_outcomes = []

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

    def push_url(self, url: str, shop_id: str | None = None, priority_id: int | None = None, *, url_type: str | None = None) -> bool:
        """Return True only for notification_accepted; never modify verdict.

        Guard the low-level entry point too: callers cannot bypass eligibility
        by invoking it directly or by submitting old priority queue entries.
        """
        self.last_notification = {"url": url, "status": "not_supported", "api_attempted": False}
        expected_type = self.allowed_pages.get(url)
        if not expected_type or url_type in {"product", "collection"}:
            self.last_notification["reason"] = "Not an explicitly allowed JobPosting or live BroadcastEvent page"
            logger.info(f"[NOT_SUPPORTED] {url}: {self.last_notification['reason']}")
            return False
        try:
            verified, reason = verify_page_type(url, expected_type)
        except Exception as exc:
            self.last_notification.update(status="validation_failed", reason=f"{type(exc).__name__}: {exc}")
            logger.warning(f"[VALIDATION_FAILED] {url}: {self.last_notification['reason']}")
            return False
        self.last_notification.update(page_type=expected_type, reason=reason)
        if not verified:
            logger.warning(f"[NOT_SUPPORTED] {url}: {reason}")
            return False

        if self.credentials is None:
            self.credentials = self._get_credentials()
        if not self.credentials.valid:
            self._refresh_token()
        # Eligibility and auth precede the existing atomic, durable reservation.
        # DB failures propagate; a reservation is never silently discarded.
        request_id = reserve_indexing_request(
            shop_id, url, INDEXING_DAILY_LIMIT, priority_id=priority_id,
        )
        if request_id is None:
            self.last_notification.update(status="quota_deferred", reason="Daily quota exhausted")
            raise IndexingQuotaExceeded
        self.last_notification.update(request_id=request_id, api_attempted=True)
        try:
            response = requests.post(
                INDEXING_ENDPOINT,
                headers={"Authorization": f"Bearer {self.credentials.token}"},
                json={"url": url, "type": "URL_UPDATED"},
                timeout=30,
            )
        except requests.RequestException as exc:
            error = str(exc)[:2000]
            complete_indexing_request(request_id, "unknown", error=error)
            self.last_notification.update(status="unknown", reason=error)
            logger.warning(f"[NOTIFICATION_UNKNOWN] {url}: {error}")
            return False

        accepted = response.status_code == 200
        error = None if accepted else response.text[:2000] or f"HTTP {response.status_code}"
        # 'succeeded' is the legacy DB outcome of the request, not an index verdict.
        complete_indexing_request(
            request_id, "succeeded" if accepted else "failed",
            http_status=response.status_code, error=error,
        )
        self.last_notification.update(
            status="notification_accepted" if accepted else "failed",
            reason="Google accepted the notification; indexing is unconfirmed" if accepted else error,
        )
        logger.info(f"[{self.last_notification['status']}] {url}: {self.last_notification['reason']}")
        return accepted

    def push_priority_batch(self, priority_rows: list[dict]) -> int:
        """Number of notifications accepted, not number of URLs indexed."""
        return self._push_rows(priority_rows, priority=True)

    def push_batch(self, urls: list[dict]) -> int:
        """Number of notifications accepted, not number of URLs indexed."""
        return self._push_rows(urls, priority=False)

    def _push_rows(self, rows, priority):
        self.last_batch_outcomes = []
        accepted = 0
        for index, row in enumerate(rows):
            url = row["url"]
            shop_id = row.get("shop_id")
            try:
                ok = self.push_url(
                    url, shop_id, priority_id=row["id"] if priority else None,
                    url_type=row.get("url_type"),
                )
            except IndexingQuotaExceeded:
                self.last_batch_outcomes.extend(
                    {"url": pending["url"], "shop_id": pending.get("shop_id"), "status": "quota_deferred"}
                    for pending in rows[index:]
                )
                break
            outcome = dict(self.last_notification, shop_id=shop_id)
            self.last_batch_outcomes.append(outcome)
            if ok:
                accepted += 1
            elif priority and outcome["status"] == "not_supported":
                mark_priority_not_supported(row["id"], outcome["reason"])
            # Non-eligible or unverifiable pages consume no quota. Failures after
            # sending have already been recorded transactionally with the request.
            if outcome["api_attempted"]:
                time.sleep(INDEXING_DELAY_SECONDS)
        return accepted
