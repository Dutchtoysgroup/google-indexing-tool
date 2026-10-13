"""Verify unsupported pages never reach the API, regardless of entry point."""

import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

from tests.support import SHOP
from config.indexing_api import get_eligible_pages
from pushers.eligibility import verify_page_type
from pushers.indexing_pusher import IndexingPusher
from scheduler.priority import schedule_priority_urls
from scheduler.strategy import get_push_urls, get_priority_push_urls
from inspectors.diagnostics import diagnose
from db.queries import complete_indexing_request
from cli import cli
from click.testing import CliRunner

JOB = "https://shop.example/jobs/designer"
PRODUCT = "https://shop.example/products/trampoline"
LIVE = "https://shop.example/live/launch"


def page(data, status=200):
    response = Mock(status_code=status)
    response.content = ('<html><script type="application/ld+json">' + json.dumps(data) + '</script></html>').encode()
    return response


class EligibilityTests(unittest.TestCase):
    def test_empty_or_missing_configuration_disables_notifications(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "indexing-pages.json"
            with patch("config.indexing_api.ELIGIBLE_PAGES_FILE", config):
                self.assertEqual(get_eligible_pages(), {})
                config.write_text("{}")
                self.assertEqual(get_eligible_pages(), {})
                config.write_text(json.dumps({PRODUCT: "Product"}))
                with self.assertRaises(ValueError):
                    get_eligible_pages()

    def test_supported_and_unsupported_structured_data(self):
        cases = [
            ({"@type": "JobPosting"}, "JobPosting", True),
            ({"@graph": [{"@type": "JobPosting"}]}, "JobPosting", True),
            ({"@type": "Product"}, "JobPosting", False),
            ([{"@type": "Product"}, {"@type": "JobPosting"}], "JobPosting", False),
            ({"@type": "ProductGroup"}, "BroadcastEvent", False),
            ({"@type": "BroadcastEvent", "isLiveBroadcast": True}, "BroadcastEvent", False),
            ({"@type": "VideoObject"}, "BroadcastEvent", False),
            ({"@type": "VideoObject", "publication": {"@type": "BroadcastEvent", "isLiveBroadcast": True}}, "BroadcastEvent", True),
            ({"@type": "VideoObject", "publication": {"@type": "BroadcastEvent", "isLiveBroadcast": False}}, "BroadcastEvent", False),
            ({"@graph": [{"@type": "VideoObject", "publication": {"@id": "#event"}}, {"@id": "#event", "@type": "BroadcastEvent", "isLiveBroadcast": True}]}, "BroadcastEvent", True),
        ]
        for data, expected_type, allowed in cases:
            with self.subTest(data=data), patch("pushers.eligibility.requests.get", return_value=page(data)):
                self.assertEqual(verify_page_type(JOB, expected_type)[0], allowed)

    def test_redirect_and_invalid_jsonld_fail_closed(self):
        bad = page({})
        bad.content = b'<script type="application/ld+json">{broken</script>'
        for response in (bad, page({"@type": "JobPosting"}, status=302)):
            with patch("pushers.eligibility.requests.get", return_value=response):
                self.assertFalse(verify_page_type(JOB, "JobPosting")[0])


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch("pushers.indexing_pusher.get_eligible_pages", return_value={JOB: "JobPosting", LIVE: "BroadcastEvent"}))
        self.auth = self.stack.enter_context(patch.object(IndexingPusher, "_get_credentials", return_value=Mock(valid=True, token="test")))
        self.get = self.stack.enter_context(patch("pushers.eligibility.requests.get", return_value=page({"@type": "JobPosting"})))
        self.post = self.stack.enter_context(patch("pushers.indexing_pusher.requests.post", return_value=Mock(status_code=200)))
        self.reserve = self.stack.enter_context(patch("pushers.indexing_pusher.reserve_indexing_request", side_effect=range(1, 100)))
        self.complete = self.stack.enter_context(patch("pushers.indexing_pusher.complete_indexing_request"))
        self.unsupported = self.stack.enter_context(patch("pushers.indexing_pusher.mark_priority_not_supported"))
        self.stack.enter_context(patch("pushers.indexing_pusher.INDEXING_DELAY_SECONDS", 0))
        self.pusher = IndexingPusher()

    def test_product_blocked_in_direct_regular_and_priority_paths(self):
        self.assertFalse(self.pusher.push_url(PRODUCT))
        self.assertEqual(self.pusher.push_batch([{"shop_id": "test", "url": PRODUCT, "url_type": "product"}]), 0)
        self.assertEqual(self.pusher.push_priority_batch([{"id": 1, "shop_id": "test", "url": PRODUCT}]), 0)
        self.post.assert_not_called()
        self.auth.assert_not_called()
        self.get.assert_not_called()
        self.reserve.assert_not_called()
        self.complete.assert_not_called()
        self.unsupported.assert_called_once()
        self.assertEqual(self.pusher.last_batch_outcomes[0]["status"], "not_supported")

    def test_allowlist_cannot_override_product_markup(self):
        self.pusher.allowed_pages[PRODUCT] = "JobPosting"
        self.get.return_value = page({"@type": "Product"})
        self.assertFalse(self.pusher.push_url(PRODUCT))
        self.post.assert_not_called()
        self.assertEqual(self.pusher.last_notification["status"], "not_supported")

    def test_known_product_type_is_blocked_even_with_job_markup(self):
        self.pusher.allowed_pages[PRODUCT] = "JobPosting"
        self.assertFalse(self.pusher.push_url(PRODUCT, url_type="product"))
        self.post.assert_not_called()

    def test_accepted_notification_does_not_claim_indexed(self):
        self.assertEqual(self.pusher.push_priority_batch([{"id": 3, "shop_id": "test", "url": JOB}]), 1)
        self.assertEqual(self.pusher.last_batch_outcomes[0]["status"], "notification_accepted")
        self.assertNotIn("indexed_status", self.pusher.last_batch_outcomes[0])
        self.reserve.assert_called_once_with("test", JOB, 200, priority_id=3)
        self.complete.assert_called_once_with(1, "succeeded", http_status=200, error=None)
        self.assertEqual(diagnose(JOB, {"verdict": "NEUTRAL"})["indexed_status"], "not_indexed")
        self.post.assert_called_once()

    def test_broadcast_in_video_is_allowed(self):
        self.get.return_value = page({"@type": "VideoObject", "publication": {"@type": "BroadcastEvent", "isLiveBroadcast": True}})
        self.assertTrue(self.pusher.push_url(LIVE))
        self.assertEqual(self.pusher.last_notification["status"], "notification_accepted")

    def test_unverifiable_page_never_reaches_api(self):
        self.get.side_effect = TimeoutError("page unavailable")
        self.assertFalse(self.pusher.push_url(JOB))
        self.post.assert_not_called()
        self.assertEqual(self.pusher.last_notification["status"], "validation_failed")

    def test_failed_requests_are_not_accepted_and_usage_belongs_to_actual_shop(self):
        self.post.side_effect = [Mock(status_code=503, text="Unavailable"), Mock(status_code=200)]
        self.get.side_effect = [page({"@type": "JobPosting"}), page({"@type": "VideoObject", "publication": {"@type": "BroadcastEvent", "isLiveBroadcast": True}})]
        self.assertEqual(self.pusher.push_batch([{"shop_id": "nl", "url": JOB}, {"shop_id": "de", "url": LIVE}]), 1)
        self.reserve.assert_any_call("nl", JOB, 200, priority_id=None)
        self.reserve.assert_any_call("de", LIVE, 200, priority_id=None)
        self.complete.assert_any_call(1, "failed", http_status=503, error="Unavailable")
        self.complete.assert_any_call(2, "succeeded", http_status=200, error=None)
        self.assertEqual([r["status"] for r in self.pusher.last_batch_outcomes], ["failed", "notification_accepted"])

    def test_zero_quota_makes_no_requests(self):
        with patch("pushers.indexing_pusher.reserve_indexing_request", return_value=None):
            self.assertEqual(self.pusher.push_batch([{"shop_id": "test", "url": JOB}]), 0)
        self.post.assert_not_called()
        self.assertEqual(self.pusher.last_batch_outcomes[0]["status"], "quota_deferred")


class SchedulingAndStatusTests(unittest.TestCase):
    def test_regular_scheduler_passes_allowlist_to_query(self):
        with patch("scheduler.strategy.get_eligible_pages", return_value={JOB: "JobPosting"}), patch("scheduler.strategy.get_daily_api_usage", return_value=0), patch("scheduler.strategy.get_urls_to_push", return_value=[]) as query:
            self.assertEqual(get_push_urls(), [])
            query.assert_called_once_with(limit=200, allowed_urls=[JOB])

    def test_empty_allowlist_disables_scheduling_and_retires_old_priority_work(self):
        with patch("scheduler.strategy.get_eligible_pages", return_value={}), patch("scheduler.strategy.exclude_unsupported_priority_urls") as exclude, patch("scheduler.strategy.get_daily_api_usage") as usage:
            self.assertEqual(get_push_urls(), [])
            self.assertEqual(get_priority_push_urls(), [])
            exclude.assert_called_once_with([])
            usage.assert_not_called()

    def test_manual_queue_rejects_product_urls(self):
        with patch("scheduler.priority.get_eligible_pages", return_value={JOB: "JobPosting"}), patch("scheduler.priority.get_shop_for_url", return_value=SHOP), patch("scheduler.priority.insert_priority_urls", return_value={"inserted": 1}) as insert:
            result = schedule_priority_urls([PRODUCT, JOB])
        self.assertEqual(insert.call_args.args[0], [(JOB, "test")])
        self.assertEqual(result["not_supported"], 1)

    def test_acceptance_storage_never_changes_inspection_verdict(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {"shop_id": "test", "url": JOB, "priority_id": 1}
        with patch("db.queries.get_connection", return_value=connection):
            complete_indexing_request(1, "succeeded", http_status=200)
        calls = cursor.execute.call_args_list
        self.assertNotIn("verdict", calls[1].args[0])
        self.assertNotIn("last_inspected", calls[1].args[0])
        self.assertEqual(calls[2].args[1][0], "notification_accepted")

    def test_missing_diagnostic_signals_remain_unknown(self):
        result = diagnose(PRODUCT, {})
        self.assertEqual(result["indexed_status"], "unknown")
        self.assertIsNone(result["noindex"])
        self.assertIsNone(result["canonical_mismatch"])

    def test_report_history_is_measured_from_snapshots(self):
        rows = [dict(date="2026-10-12", total_urls=20, indexed_count=10, unknown_count=5), dict(date="2026-10-13", total_urls=20, indexed_count=12, unknown_count=3)]
        stats = dict(total_urls=20, indexed=12, not_indexed=5, not_checked=3, removed=0)
        with patch("cli.init_db"), patch("cli.get_shop_by_id", return_value=SHOP), patch("cli.get_shop_summary", return_value=stats), patch("cli.get_snapshot_history", return_value=rows):
            result = CliRunner().invoke(cli, ["report", "--shop", "test", "--history", "30"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("+2", result.output)
        self.assertIn("dit bewijst geen versnelling", result.output)
