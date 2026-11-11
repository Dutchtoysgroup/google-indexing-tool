"""De nachtelijke trigger start een run, wacht kort en meldt de vorige uitkomst."""

import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "trigger_azure_webjob", Path(__file__).parent.parent / "scripts" / "trigger_azure_webjob.py"
)
trigger = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trigger)


class Closable:
    def close(self):
        pass


class TriggerTests(unittest.TestCase):
    def run_main(self, history, *, key_staged=(False,), env=None):
        """history: opeenvolgende antwoorden van latest_run()."""
        calls = []
        runs = iter(history)
        last = [None]

        def latest():
            try:
                last[0] = next(runs)
            except StopIteration:
                pass
            return last[0]

        def request(path, method="GET", data=None, headers=None):
            calls.append((method, path))
            return Closable()

        clock = [0.0]

        def sleep(seconds):
            clock[0] += seconds

        staged = iter(key_staged)
        staged_last = [False]

        def is_staged():
            try:
                staged_last[0] = next(staged)
            except StopIteration:
                pass
            return staged_last[0]

        variables = {"GOOGLE_SERVICE_ACCOUNT_KEY": "sleutel", "WAIT_MINUTES": "1", **(env or {})}
        with patch.dict(os.environ, variables), \
             patch.object(trigger, "latest_run", latest), \
             patch.object(trigger, "request", request), \
             patch.object(trigger, "key_is_staged", is_staged), \
             patch.object(trigger.time, "sleep", sleep), \
             patch.object(trigger.time, "monotonic", lambda: clock[0]), \
             patch("builtins.print"):
            code = trigger.main()
        return code, calls

    def test_long_run_returns_success_once_key_is_consumed(self):
        old = {"id": "1", "status": "Success"}
        new = {"id": "2", "status": "Running"}
        code, calls = self.run_main([old, old, new])
        self.assertEqual(code, 0)
        self.assertIn(("POST", trigger.JOB_PATH), calls)
        # De lopende run moet de sleutel nog kunnen lezen: niet weghalen.
        self.assertNotIn(("DELETE", trigger.SECRET_PATH), calls)

    def test_previous_failure_fails_the_nightly_workflow_but_still_starts(self):
        old = {"id": "1", "status": "Failed"}
        new = {"id": "2", "status": "Running"}
        code, calls = self.run_main([old, new], env={"REQUIRE_PREVIOUS_SUCCESS": "1"})
        self.assertEqual(code, 1)
        self.assertIn(("POST", trigger.JOB_PATH), calls)
        code, _ = self.run_main([old, new], env={"REQUIRE_PREVIOUS_SUCCESS": "0"})
        self.assertEqual(code, 0)

    def test_run_still_in_progress_is_not_started_twice(self):
        with self.assertRaisesRegex(RuntimeError, "loopt nog"):
            self.run_main([{"id": "1", "status": "Running"}])

    def test_quick_failure_is_reported_and_key_removed(self):
        old = {"id": "1", "status": "Success"}
        code, calls = self.run_main([old, {"id": "2", "status": "Failed"}])
        self.assertEqual(code, 1)
        self.assertIn(("DELETE", trigger.SECRET_PATH), calls)

    def test_run_that_never_appears_fails_and_removes_key(self):
        old = {"id": "1", "status": "Success"}
        code, calls = self.run_main([old])
        self.assertEqual(code, 1)
        self.assertIn(("DELETE", trigger.SECRET_PATH), calls)

    def test_trigger_error_removes_key(self):
        def request(path, method="GET", data=None, headers=None):
            if method == "POST":
                raise RuntimeError("Kudu POST gaf HTTP 409")
            deleted.append(method) if method == "DELETE" else None
            return Closable()

        deleted = []
        with patch.dict(os.environ, {"GOOGLE_SERVICE_ACCOUNT_KEY": "sleutel"}), \
             patch.object(trigger, "latest_run", lambda: None), \
             patch.object(trigger, "request", request), patch("builtins.print"):
            with self.assertRaisesRegex(RuntimeError, "409"):
                trigger.main()
        self.assertEqual(deleted, ["DELETE"])


if __name__ == "__main__":
    unittest.main()
