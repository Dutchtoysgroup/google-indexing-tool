import unittest
from types import SimpleNamespace
from unittest.mock import patch

import requests

from tests.support import response
from pushers.indexing_pusher import IndexingPusher


def pusher():
    result = IndexingPusher.__new__(IndexingPusher)
    result.credentials = SimpleNamespace(valid=True, token="test-token")
    return result


ROWS = [{"shop_id": "A", "url": "https://a.example/p"},
        {"shop_id": "B", "url": "https://b.example/p"}]


class PushTests(unittest.TestCase):
    def test_mixed_results_are_recorded_for_the_actual_request(self):
        with patch("pushers.indexing_pusher.reserve_indexing_request", side_effect=[10, 11]) as reserve, patch(
            "pushers.indexing_pusher.complete_indexing_request"
        ) as complete, patch("pushers.indexing_pusher.requests.post", side_effect=[
            response("unavailable", 503), response("{}", 200),
        ]), patch("pushers.indexing_pusher.time.sleep"):
            self.assertEqual(pusher().push_batch(ROWS), 1)
        self.assertEqual([call.args[:2] for call in reserve.call_args_list], [
            ("A", ROWS[0]["url"]), ("B", ROWS[1]["url"]),
        ])
        self.assertEqual([call.args for call in complete.call_args_list], [
            (10, "failed"), (11, "succeeded"),
        ])

    def test_no_request_when_budget_cannot_be_reserved(self):
        with patch("pushers.indexing_pusher.reserve_indexing_request", return_value=None), patch(
            "pushers.indexing_pusher.requests.post"
        ) as post:
            self.assertEqual(pusher().push_batch(ROWS), 0)
        post.assert_not_called()

    def test_no_request_when_reservation_fails(self):
        with patch("pushers.indexing_pusher.reserve_indexing_request", side_effect=RuntimeError("db down")), patch(
            "pushers.indexing_pusher.requests.post"
        ) as post:
            with self.assertRaises(RuntimeError):
                pusher().push_batch(ROWS)
        post.assert_not_called()

    def test_timeout_is_unknown_and_keeps_reservation(self):
        with patch("pushers.indexing_pusher.reserve_indexing_request", return_value=10), patch(
            "pushers.indexing_pusher.complete_indexing_request"
        ) as complete, patch("pushers.indexing_pusher.requests.post", side_effect=requests.Timeout("timeout")), patch(
            "pushers.indexing_pusher.time.sleep"
        ):
            self.assertEqual(pusher().push_batch(ROWS[:1]), 0)
        complete.assert_called_once_with(10, "unknown", error="timeout")

    def test_token_refresh_failure_consumes_no_budget(self):
        instance = pusher()
        instance.credentials.valid = False
        with patch.object(instance, "_refresh_token", side_effect=RuntimeError("auth failed")), patch(
            "pushers.indexing_pusher.reserve_indexing_request"
        ) as reserve:
            with self.assertRaises(RuntimeError):
                instance.push_batch(ROWS)
        reserve.assert_not_called()
