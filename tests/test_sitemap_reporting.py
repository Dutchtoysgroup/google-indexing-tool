import unittest
import json
import os
import tempfile
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from tests.support import SHOP
from collectors.sitemap import SitemapResult
from cli import cli
import main


class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        environment = patch.dict(os.environ, {"PIPELINE_REPORT_DIR": self.directory.name})
        environment.start()
        self.addCleanup(environment.stop)

    def result(self, complete):
        return SitemapResult(
            urls={"product": [SHOP.base_url + "/product"]},
            failed_sitemaps=[] if complete else [SHOP.base_url + "/sitemap-products.xml"],
        )

    def test_scan_cli_reports_incomplete_and_exits_nonzero(self):
        with patch("cli.init_db"), patch("cli.get_enabled_shops", return_value=[SHOP]), patch(
            "cli.SitemapCollector.collect", return_value=self.result(False)
        ):
            result = CliRunner().invoke(cli, ["scan"])
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn("INCOMPLEET; bestaande URLs behouden", result.output)
        self.assertIn("Sitemapscan incompleet: test", result.output)

    def test_cli_pipeline_reports_incomplete_after_other_stages(self):
        with ExitStack() as stack:
            for name, value in {
                "init_db": None, "get_enabled_shops": [SHOP],
                "SitemapCollector.collect": self.result(False),
                "URLInspector": MagicMock(), "IndexingPusher": MagicMock(),
                "get_inspection_urls": [], "get_priority_push_urls": [],
                "get_push_urls": [], "get_all_shops_summary": [],
            }.items():
                stack.enter_context(patch("main." + name, return_value=value))
            snapshot = stack.enter_context(patch("main.save_daily_snapshot"))
            result = CliRunner().invoke(cli, ["run"])
        self.assertEqual(result.exit_code, 1, result.output)
        report_path, = Path(self.directory.name).glob("*.json")
        report = json.loads(report_path.read_text())
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["shops"]["test"]["phases"]["scan"]["failed_sitemaps"],
                         [SHOP.base_url + "/sitemap-products.xml"])
        snapshot.assert_called_once_with("test")

    def test_main_pipeline_exit_status_and_final_report(self):
        for complete in (False, True):
            with self.subTest(complete=complete), ExitStack() as stack:
                for name, value in {
                    "setup_logging": None, "init_db": None,
                    "get_time_budget_seconds": None, "get_enabled_shops": [SHOP],
                    "SitemapCollector.collect": self.result(complete),
                    "URLInspector": MagicMock(), "IndexingPusher": MagicMock(),
                    "get_inspection_urls": [], "get_priority_push_urls": [],
                    "get_push_urls": [], "get_all_shops_summary": [],
                }.items():
                    stack.enter_context(patch("main." + name, return_value=value))
                snapshot = stack.enter_context(patch("main.save_daily_snapshot"))
                with self.assertLogs("main", level="INFO") as logs:
                    code = main.main()
                self.assertEqual(code, 0 if complete else 1)
                self.assertEqual("Pipeline incomplete" in " ".join(logs.output), not complete)
                snapshot.assert_called_once_with("test")
