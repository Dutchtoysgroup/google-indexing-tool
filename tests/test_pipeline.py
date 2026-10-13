"""Offline regression tests: no Google credentials or database required."""

import json
import os
import runpy
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, mock_open, patch

import requests
from click.testing import CliRunner

# shops.py eagerly reads user configuration. Bootstrap with an empty fixture;
# individual tests supply their own shops without reading/writing real config.
with patch.object(Path, "exists", return_value=True), patch.object(Path, "open", mock_open(read_data="[]")):
    from config.shops import Shop

import cli
import main
from collectors.sitemap import SitemapCollector, SitemapResult
from inspectors.url_inspector import URLInspector
from pipeline_report import RunReport

REAL_COLLECT = SitemapCollector.collect

SHOPS = [
    Shop("shop_nl", "Shop NL", "https://shop.nl", "https://shop.nl/", "nl-NL"),
    Shop("shop_de", "Shop DE", "https://shop.de", "https://shop.de/", "de-DE"),
]


def api_response(verdict="PASS"):
    response = Mock()
    response.json.return_value = {"inspectionResult": {"indexStatusResult": {"verdict": verdict}}}
    return response


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.dict(os.environ, {"PIPELINE_REPORT_DIR": str(self.directory), "TIME_BUDGET_MINUTES": ""}))
        self.stack.enter_context(patch("main.get_enabled_shops", return_value=SHOPS))
        self.init = self.stack.enter_context(patch("main.init_db"))
        self.collect = self.stack.enter_context(patch("main.SitemapCollector.collect", return_value=SitemapResult(urls={"product": ["https://shop.nl/a"]})))
        self.select = self.stack.enter_context(patch("main.get_inspection_urls", side_effect=lambda sid: [{"url": f"https://{sid}/a"}]))
        self.stack.enter_context(patch("main.get_priority_push_urls", return_value=[]))
        self.stack.enter_context(patch("main.get_push_urls", return_value=[]))
        self.snapshot = self.stack.enter_context(patch("main.save_daily_snapshot"))
        self.stack.enter_context(patch("main.get_all_shops_summary", return_value=[]))
        self.stack.enter_context(patch.object(URLInspector, "_get_credentials", return_value=Mock(valid=True, token="test")))
        self.stack.enter_context(patch.object(URLInspector, "_refresh_token"))
        self.usage = self.stack.enter_context(patch("inspectors.url_inspector.get_daily_api_usage", return_value=0))
        self.update = self.stack.enter_context(patch("inspectors.url_inspector.update_inspection_result"))
        self.stack.enter_context(patch("inspectors.url_inspector.log_api_usage"))
        self.stack.enter_context(patch("inspectors.url_inspector.INSPECTION_DELAY_SECONDS", 0))
        self.post = self.stack.enter_context(patch("inspectors.url_inspector.requests.post", return_value=api_response()))

    def report(self):
        reports = list(self.directory.glob("*.json"))
        self.assertEqual(len(reports), 1)
        return json.loads(reports[0].read_text())

    def test_success_and_nonindexed_verdict_are_not_api_failures(self):
        self.post.return_value = api_response("FAIL")
        self.assertEqual(main.main(), 0)
        self.assertEqual(self.report()["status"], "success")
        self.assertEqual(self.snapshot.call_count, 2)

    def test_api_outage_is_durable_and_shop_specific(self):
        self.post.side_effect = requests.HTTPError("503 Service Unavailable")
        with self.assertLogs("main", level="INFO") as logs:
            self.assertEqual(main.main(), 1)
        report = self.report()
        self.assertEqual(report["status"], "incomplete")
        for shop in SHOPS:
            phases = report["shops"][shop.shop_id]["phases"]
            self.assertEqual(phases["inspect"]["status"], "failed")
            self.assertEqual(phases["inspect"]["attempted"], 1)
            self.assertEqual(phases["inspect"]["succeeded"], 0)
            self.assertIn("503", phases["inspect"]["errors"][0]["error"])
            self.assertIn(shop.shop_id, phases["inspect"]["errors"][0]["url"])
            self.assertEqual(phases["snapshot"]["status"], "success")
        self.assertFalse(any("Pipeline voltooid" in line for line in logs.output))
        self.update.assert_not_called()

    def test_partial_api_outage_marks_only_affected_shop(self):
        self.select.side_effect = lambda sid: [{"url": f"https://{sid}/a"}, {"url": f"https://{sid}/b"}]
        self.post.side_effect = [api_response(), requests.Timeout("inspection timed out"), api_response(), api_response()]
        self.assertEqual(main.main(), 1)
        report = self.report()
        phase = report["shops"]["shop_nl"]["phases"]["inspect"]
        self.assertEqual(phase["status"], "incomplete")
        self.assertEqual(phase["succeeded"], 1)
        self.assertEqual(phase["attempted"], 2)
        self.assertEqual(report["shops"]["shop_de"]["status"], "success")

    def test_scan_and_snapshot_failure_do_not_stop_other_shops(self):
        self.collect.side_effect = [requests.ConnectionError("sitemap unavailable"), SitemapResult()]
        self.snapshot.side_effect = [RuntimeError("snapshot write failed"), None]
        self.assertEqual(main.main(), 1)
        report = self.report()
        self.assertEqual(report["shops"]["shop_nl"]["phases"]["scan"]["status"], "failed")
        self.assertIn("snapshot write failed", report["shops"]["shop_nl"]["phases"]["snapshot"]["error"])
        self.assertEqual(report["shops"]["shop_de"]["status"], "success")

    def test_auth_failure_is_recorded_per_shop(self):
        with patch.object(URLInspector, "_refresh_token", side_effect=RuntimeError("credentials unavailable")):
            self.assertEqual(main.main(), 1)
        for shop in self.report()["shops"].values():
            self.assertIn("credentials unavailable", shop["phases"]["inspect"]["error"])
        self.assertEqual(self.snapshot.call_count, 2)

    def test_malformed_api_result_is_not_success(self):
        self.post.return_value.json.return_value = {}
        self.assertEqual(main.main(), 1)
        phase = self.report()["shops"]["shop_nl"]["phases"]["inspect"]
        self.assertIn("missing indexStatusResult.verdict", phase["errors"][0]["error"])

    def test_time_budget_skips_are_incomplete_but_snapshots_run(self):
        with patch("main.get_time_budget_seconds", return_value=1), patch("main.time.monotonic", side_effect=[0] + [2] * 20):
            self.assertEqual(main.main(), 1)
        for shop in self.report()["shops"].values():
            self.assertEqual(shop["phases"]["scan"]["reason"], "time_budget_exceeded")
            self.assertEqual(shop["phases"]["inspect"]["status"], "skipped")
            self.assertEqual(shop["phases"]["snapshot"]["status"], "success")
        self.post.assert_not_called()

    def test_quota_exhaustion_is_normal_scheduling(self):
        self.usage.return_value = 2000
        self.assertEqual(main.main(), 0)
        self.post.assert_not_called()
        self.assertEqual(self.report()["shops"]["shop_nl"]["phases"]["inspect"]["skipped"], 1)

    def test_no_work_does_not_require_google_auth(self):
        self.select.side_effect = None
        self.select.return_value = []
        with patch("main.URLInspector", side_effect=AssertionError("no auth needed")):
            self.assertEqual(main.main(), 0)

    def test_push_failure_remains_optional_and_snapshots_run(self):
        with patch("main.get_priority_push_urls", side_effect=RuntimeError("push unavailable")):
            self.assertEqual(main.main(), 0)
        self.assertEqual(self.report()["push"]["status"], "failed")
        self.assertEqual(self.snapshot.call_count, 2)

    def test_database_init_failure_is_durable_and_failed(self):
        self.init.side_effect = RuntimeError("database unavailable")
        self.assertEqual(main.main(), 1)
        self.assertEqual(self.report()["status"], "failed")
        self.assertIn("database unavailable", self.report()["errors"][0]["error"])

    def test_summary_failure_is_durable_and_failed(self):
        with patch("main.get_all_shops_summary", side_effect=RuntimeError("summary unavailable")):
            self.assertEqual(main.main(), 1)
        self.assertEqual(self.report()["status"], "failed")
        self.assertEqual(self.report()["errors"][0]["phase"], "summary")
        self.assertEqual(self.snapshot.call_count, 2)

    def test_no_enabled_shops_cannot_report_success(self):
        with patch("main.get_enabled_shops", return_value=[]):
            self.assertEqual(main.main(), 1)
        self.assertEqual(self.report()["status"], "failed")

    def test_all_required_phases_failing_marks_run_failed(self):
        self.collect.side_effect = requests.Timeout("sitemap unavailable")
        self.post.side_effect = requests.Timeout("Google unavailable")
        self.snapshot.side_effect = RuntimeError("snapshot unavailable")
        self.assertEqual(main.main(), 1)
        self.assertEqual(self.report()["status"], "failed")
        self.assertTrue(all(s["status"] == "failed" for s in self.report()["shops"].values()))

    def test_cli_propagates_real_pipeline_failure(self):
        self.post.side_effect = requests.Timeout("Google unavailable")
        result = CliRunner().invoke(cli.cli, ["run"])
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertEqual(self.report()["status"], "incomplete")

    def test_main_entrypoint_uses_pipeline_exit_code(self):
        # runpy creates a fresh main module, so patch its imported dependencies.
        with patch("config.shops.get_enabled_shops", return_value=SHOPS), \
             patch("db.models.init_db"), \
             patch("db.queries.save_daily_snapshot"), \
             patch("db.queries.get_all_shops_summary", return_value=[]), \
             patch("scheduler.strategy.get_inspection_urls", return_value=[{"url": "https://shop.nl/a"}]), \
             patch("scheduler.strategy.get_priority_push_urls", return_value=[]), \
             patch("scheduler.strategy.get_push_urls", return_value=[]):
            self.post.side_effect = requests.HTTPError("503 Service Unavailable")
            with self.assertRaises(SystemExit) as result:
                runpy.run_module("main", run_name="__main__")
            self.assertEqual(result.exception.code, 1)
        self.assertEqual(self.report()["status"], "incomplete")

    def test_reports_survive_reopening_and_runs_do_not_overwrite(self):
        first = RunReport(SHOPS)
        first.phase("shop_nl", "scan", "running")
        persisted = json.loads(first.path.read_text())
        self.assertEqual(persisted["status"], "incomplete")
        self.assertIsNone(persisted["finished_at"])
        self.assertEqual(persisted["shops"]["shop_nl"]["phases"]["scan"]["status"], "running")
        second = RunReport(SHOPS)
        self.assertNotEqual(first.path, second.path)
        self.assertTrue(first.path.exists())

    def test_persistence_failure_cannot_return_success(self):
        with patch("pipeline_report.os.replace", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                main.main()
        self.collect.assert_not_called()

    def test_real_collector_partial_failure_reaches_durable_report(self):
        # Remove only the inherited collector mock; all external writes remain mocked.
        self.collect.side_effect = None
        # The original method is captured before setUp installs the mock.
        with patch("main.SitemapCollector.collect", REAL_COLLECT), \
             patch("collectors.sitemap.apply_sitemap_snapshot") as apply, \
             patch("requests.Session.get") as get:
            root = Mock(content=b'<sitemapindex><sitemap><loc>https://shop.nl/products.xml</loc></sitemap><sitemap><loc>https://shop.nl/pages.xml</loc></sitemap></sitemapindex>')
            child = Mock(content=b'<urlset><url><loc>https://shop.nl/a</loc></url></urlset>')
            get.side_effect = [root, child, requests.HTTPError("503 Service Unavailable"), requests.Timeout("root unavailable")]
            self.assertEqual(main.main(), 1)
        report = self.report()
        scan = report["shops"]["shop_nl"]["phases"]["scan"]
        self.assertEqual(scan["status"], "incomplete")
        self.assertEqual(scan["url_count"], 1)
        self.assertEqual(scan["failed_sitemaps"], ["https://shop.nl/pages.xml"])
        self.assertIn("503", scan["errors"][0]["error"])
        self.assertEqual(report["shops"]["shop_de"]["phases"]["scan"]["status"], "failed")
        self.assertTrue(all(not call.kwargs["complete"] for call in apply.call_args_list))
        self.assertEqual(self.snapshot.call_count, 2)


if __name__ == "__main__":
    unittest.main()
