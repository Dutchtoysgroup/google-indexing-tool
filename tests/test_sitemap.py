import unittest
from unittest.mock import patch

from tests.support import BASE, ROOT, PRODUCTS, PAGES, SHOP, xml, response, install_responses
from collectors.sitemap import SitemapCollector
import requests


class SitemapTests(unittest.TestCase):
    def collect(self, responses):
        collector = SitemapCollector()
        install_responses(collector, responses)
        with patch("collectors.sitemap.apply_sitemap_snapshot") as apply:
            result = collector.collect(SHOP)
        return result, apply

    def test_child_503_reports_incomplete_and_passes_status_to_staging(self):
        with self.assertLogs("collectors.sitemap", level="WARNING") as logs:
            result, apply = self.collect({
                ROOT: response(xml("sitemapindex", [PRODUCTS, PAGES])),
                PRODUCTS: response(status=503),
                PAGES: response(xml("urlset", [BASE + "/about"])),
            })
        self.assertFalse(result.complete)
        self.assertEqual(result.failed_sitemaps, [PRODUCTS])
        self.assertEqual(result.urls, {"page": [BASE + "/about"]})
        apply.assert_called_once_with("test", [(BASE + "/about", "page")], complete=False)
        self.assertIn("incompleet", " ".join(logs.output))

    def test_nested_failure_propagates(self):
        nested = BASE + "/nested.xml"
        result, _ = self.collect({
            ROOT: response(xml("sitemapindex", [nested, PAGES])),
            nested: response(xml("sitemapindex", [PRODUCTS])),
            PRODUCTS: response(status=503),
            PAGES: response(xml("urlset", [BASE + "/about"])),
        })
        self.assertFalse(result.complete)
        self.assertEqual(result.failed_sitemaps, [PRODUCTS])

    def test_invalid_or_empty_child_never_becomes_complete(self):
        for body in ["", "<urlset/>", "<sitemapindex/>", "<html/>",
                     '<urlset><url><loc>https://shop.example/a</loc></url>',
                     "<urlset><url/></urlset>",
                     "<urlset><url><loc> </loc></url></urlset>",
                     xml("urlset", ["https://shop.example.evil/a"])]:
            with self.subTest(body=body):
                result, apply = self.collect({
                    ROOT: response(xml("sitemapindex", [PRODUCTS, PAGES])),
                    PRODUCTS: response(body),
                    PAGES: response(xml("urlset", [BASE + "/about"])),
                })
                self.assertFalse(result.complete)
                self.assertFalse(apply.call_args.kwargs["complete"])

    def test_root_http_error_and_timeout_are_incomplete(self):
        for failure in [response(status=503), requests.Timeout("timeout")]:
            with self.subTest(failure=failure):
                result, apply = self.collect({ROOT: failure})
                self.assertFalse(result.complete)
                self.assertEqual(result.total, 0)
                apply.assert_called_once_with("test", [], complete=False)

    def test_direct_sitemap_and_image_locations(self):
        result, apply = self.collect({ROOT: response(
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
            'xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">'
            f'<url><loc>{BASE}/product</loc><image:image>'
            f'<image:loc>{BASE}/image.jpg</image:loc></image:image></url></urlset>'
        )})
        self.assertTrue(result.complete)
        self.assertEqual(result.urls, {"other": [BASE + "/product"]})
        apply.assert_called_once_with("test", [(BASE + "/product", None)], complete=True)

    def test_full_scan_deduplicates_and_keeps_types(self):
        result, apply = self.collect({
            ROOT: response(xml("sitemapindex", [PRODUCTS, PAGES, PRODUCTS])),
            PRODUCTS: response(xml("urlset", [BASE + "/product", BASE + "/product"])),
            PAGES: response(xml("urlset", [BASE + "/about"])),
        })
        self.assertTrue(result.complete)
        self.assertEqual(result.total, 2)
        self.assertEqual(result.urls["product"], [BASE + "/product"])
        self.assertTrue(apply.call_args.kwargs["complete"])

    def test_cycle_is_incomplete(self):
        result, _ = self.collect({ROOT: response(xml("sitemapindex", [ROOT]))})
        self.assertFalse(result.complete)

    def test_missing_index_location_is_incomplete(self):
        result, _ = self.collect({
            ROOT: response('<sitemapindex><sitemap/><sitemap><loc>' + PRODUCTS +
                           '</loc></sitemap></sitemapindex>'),
            PRODUCTS: response(xml("urlset", [BASE + "/product"])),
        })
        self.assertFalse(result.complete)
        self.assertEqual(result.total, 1)
