"""Duurzaamheid, atomiciteit en concurrent budgetgebruik in lokale PostgreSQL."""

import os
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from unittest.mock import patch

import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from tests.support import response
from tests.test_indexing_pusher import pusher, ROWS
from db.models import SCHEMA_SQL
from db.queries import (
    reserve_indexing_request, complete_indexing_request,
    get_daily_api_usage, get_daily_indexing_outcomes, log_api_usage,
    get_urls_to_push, exclude_unsupported_priority_urls, get_snapshot_history,
)


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "TEST_DATABASE_URL ontbreekt")
class IndexingDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.dsn = os.environ["TEST_DATABASE_URL"]
        self.schema = "test_indexing_" + uuid4().hex
        self.admin = psycopg2.connect(self.dsn)
        self.admin.autocommit = True
        with self.admin.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
            cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(self.schema)))
            cur.execute(SCHEMA_SQL)
            for row in ROWS:
                cur.execute("INSERT INTO urls (shop_id, url) VALUES (%s, %s)", (row["shop_id"], row["url"]))
        self.db_patch = patch("db.queries.get_connection", side_effect=self.connect)
        self.db_patch.start()
        self.delay_patch = patch("pushers.indexing_pusher.INDEXING_DELAY_SECONDS", 0)
        self.delay_patch.start()
        verification = patch("pushers.indexing_pusher.verify_page_type", return_value=(True, "Verified JobPosting"))
        verification.start()
        self.addCleanup(verification.stop)

    def connect(self):
        return psycopg2.connect(
            self.dsn, options=f"-c search_path={self.schema}", cursor_factory=RealDictCursor,
        )

    def tearDown(self):
        self.db_patch.stop()
        self.delay_patch.stop()
        with self.admin.cursor() as cur:
            cur.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))
        self.admin.close()

    def rows(self, query):
        with self.admin.cursor() as cur:
            cur.execute(query)
            return cur.fetchall()

    def test_a_fails_b_succeeds_and_each_attempt_consumes_budget(self):
        with patch("pushers.indexing_pusher.requests.post", side_effect=[response("bad", 400), response("{}")]):
            self.assertEqual(pusher().push_batch(ROWS), 1)
        self.assertEqual(self.rows("SELECT shop_id, push_count, last_pushed IS NOT NULL FROM urls ORDER BY shop_id"), [
            ("A", 0, False), ("B", 1, True),
        ])
        self.assertEqual(self.rows("SELECT shop_id, url, outcome, http_status FROM indexing_requests ORDER BY id"), [
            ("A", ROWS[0]["url"], "failed", 400), ("B", ROWS[1]["url"], "succeeded", 200),
        ])
        self.assertEqual(get_daily_api_usage("indexing", "A"), 1)
        self.assertEqual(get_daily_api_usage("indexing", "B"), 1)
        self.assertEqual(get_daily_indexing_outcomes("A")["succeeded"], 0)
        self.assertEqual(get_daily_indexing_outcomes("B")["succeeded"], 1)

    def test_concurrent_workers_cannot_overbook_remaining_budget(self):
        log_api_usage("legacy", "indexing", 2)
        with ThreadPoolExecutor(max_workers=12) as pool:
            reserved = list(pool.map(
                lambda i: reserve_indexing_request("A", f"https://a.example/{i}", 5), range(12),
            ))
        self.assertEqual(sum(request_id is not None for request_id in reserved), 3)
        self.assertEqual(get_daily_api_usage("indexing"), 5)
        self.assertEqual(self.rows("SELECT count(*) FROM indexing_requests"), [(3,)])

    def test_hard_process_exit_keeps_previous_success_and_inflight_budget(self):
        script = '''
import os
from unittest.mock import patch
from tests.test_indexing_pusher import pusher, ROWS
from tests.support import response
import psycopg2
from psycopg2.extras import RealDictCursor

def connect():
    return psycopg2.connect(os.environ["TEST_DATABASE_URL"],
        options="-c search_path=" + os.environ["TEST_SCHEMA"], cursor_factory=RealDictCursor)

calls = 0
def post(*args, **kwargs):
    global calls
    calls += 1
    if calls == 2:
        os._exit(17)
    return response("{}")

with patch("db.queries.get_connection", side_effect=connect), patch(
    "pushers.indexing_pusher.requests.post", side_effect=post
), patch("pushers.indexing_pusher.INDEXING_DELAY_SECONDS", 0), patch(
    "pushers.indexing_pusher.verify_page_type", return_value=(True, "Verified JobPosting")
):
    pusher().push_batch(ROWS)
'''
        env = {**os.environ, "TEST_SCHEMA": self.schema}
        result = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 17, result.stderr)
        self.assertEqual(get_daily_api_usage("indexing"), 2)
        self.assertEqual(self.rows("SELECT shop_id, outcome FROM indexing_requests ORDER BY id"), [
            ("A", "succeeded"), ("B", "reserved"),
        ])
        self.assertEqual(self.rows("SELECT shop_id, push_count FROM urls ORDER BY shop_id"), [("A", 1), ("B", 0)])
        self.assertIsNone(reserve_indexing_request("B", ROWS[1]["url"], 2))

    def test_completion_is_idempotent(self):
        request_id = reserve_indexing_request("A", ROWS[0]["url"], 5)
        complete_indexing_request(request_id, "succeeded", http_status=200)
        complete_indexing_request(request_id, "succeeded", http_status=200)
        self.assertEqual(self.rows("SELECT push_count FROM urls WHERE shop_id = 'A'"), [(1,)])
        self.assertEqual(get_daily_api_usage("indexing"), 1)
        self.assertEqual(get_daily_indexing_outcomes()["succeeded"], 1)

    def test_failed_completion_rolls_back_outcome_but_keeps_budget(self):
        request_id = reserve_indexing_request("A", ROWS[0]["url"], 5)
        with self.admin.cursor() as cur:
            cur.execute("ALTER TABLE urls ADD CONSTRAINT reject_push CHECK (push_count = 0)")
        with self.assertRaises(psycopg2.Error):
            complete_indexing_request(request_id, "succeeded", http_status=200)
        self.assertEqual(self.rows("SELECT outcome FROM indexing_requests"), [("reserved",)])
        self.assertEqual(get_daily_api_usage("indexing"), 1)
        self.assertEqual(get_daily_indexing_outcomes()["succeeded"], 0)

    def test_failed_reservation_leaves_no_request_or_usage(self):
        with self.admin.cursor() as cur:
            cur.execute("ALTER TABLE api_log ADD CONSTRAINT reject_usage CHECK (url_count = 0)")
        with self.assertRaises(psycopg2.Error):
            reserve_indexing_request("A", ROWS[0]["url"], 5)
        self.assertEqual(self.rows("SELECT count(*) FROM indexing_requests"), [(0,)])
        self.assertEqual(get_daily_api_usage("indexing"), 0)

    def test_priority_and_regular_pushes_share_budget_and_correct_results(self):
        priority = []
        with self.admin.cursor() as cur:
            for row in ROWS:
                cur.execute("INSERT INTO priority_urls (shop_id, url) VALUES (%s, %s) RETURNING id", (row["shop_id"], row["url"]))
                priority.append({**row, "id": cur.fetchone()[0]})
        with patch("pushers.indexing_pusher.INDEXING_DAILY_LIMIT", 2), patch(
            "pushers.indexing_pusher.requests.post", side_effect=[response("bad", 403), response("{}")]
        ) as post:
            self.assertEqual(pusher().push_priority_batch(priority), 1)
            self.assertEqual(pusher().push_batch(ROWS), 0)
            self.assertEqual(post.call_count, 2)
        self.assertEqual(self.rows("SELECT shop_id, status, pushed_at IS NOT NULL FROM priority_urls ORDER BY id"), [
            ("A", "failed", False), ("B", "notification_accepted", True),
        ])
        self.assertEqual(get_daily_indexing_outcomes("A")["succeeded"], 0)
        self.assertEqual(get_daily_indexing_outcomes("B")["succeeded"], 1)

    def test_unmapped_priority_attempt_is_counted_without_shop_success(self):
        with self.admin.cursor() as cur:
            cur.execute("INSERT INTO priority_urls (url) VALUES ('https://unknown.example/p') RETURNING id")
            priority_id = cur.fetchone()[0]
        with patch("pushers.indexing_pusher.requests.post", return_value=response("{}")):
            self.assertEqual(pusher().push_priority_batch([{"id": priority_id, "url": "https://unknown.example/p"}]), 1)
        self.assertEqual(get_daily_api_usage("indexing", "__priority_unmapped__"), 1)
        self.assertEqual(get_daily_indexing_outcomes()["succeeded"], 1)
        self.assertEqual(get_daily_indexing_outcomes("A")["succeeded"], 0)


    def test_product_selection_and_legacy_queue_are_excluded(self):
        with self.admin.cursor() as cur:
            cur.execute("UPDATE urls SET verdict = 'NEUTRAL', url_type = CASE shop_id WHEN 'A' THEN 'product' ELSE 'page' END")
            for row in ROWS:
                cur.execute("INSERT INTO priority_urls (shop_id, url) VALUES (%s, %s)", (row["shop_id"], row["url"]))
        allowed = [r["url"] for r in ROWS]
        self.assertEqual([r["shop_id"] for r in get_urls_to_push(allowed_urls=allowed)], ["B"])
        exclude_unsupported_priority_urls(allowed)
        self.assertEqual(self.rows("SELECT shop_id, status FROM priority_urls ORDER BY shop_id"), [("A", "not_supported"), ("B", "pending")])
        exclude_unsupported_priority_urls([])
        self.assertEqual(self.rows("SELECT COUNT(*) FROM priority_urls WHERE status = 'not_supported'"), [(2,)])

    def test_notification_acceptance_does_not_change_measured_indexing(self):
        with self.admin.cursor() as cur:
            cur.execute("UPDATE urls SET verdict = 'NEUTRAL'")
        request_id = reserve_indexing_request("A", ROWS[0]["url"], 5)
        complete_indexing_request(request_id, "succeeded", http_status=200)
        self.assertEqual(self.rows("SELECT verdict FROM urls WHERE shop_id = 'A'"), [("NEUTRAL",)])
        self.assertEqual(get_daily_indexing_outcomes()["notification_accepted"], 1)

    def test_snapshot_history_reads_measured_counts(self):
        with self.admin.cursor() as cur:
            cur.execute("INSERT INTO daily_snapshots (shop_id, date, total_urls, indexed_count) VALUES ('A', CURRENT_DATE, 10, 3)")
        history = get_snapshot_history("A", 30)
        self.assertEqual(history[0]["indexed_count"], 3)
        self.assertEqual(history[0]["total_urls"], 10)
