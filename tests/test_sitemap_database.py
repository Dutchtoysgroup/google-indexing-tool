"""Run met TEST_DATABASE_URL naar een uitsluitend lokale testdatabase."""

import os
import unittest
from uuid import uuid4
from unittest.mock import patch

import psycopg2
from psycopg2 import sql

from tests.support import BASE, ROOT, PRODUCTS, PAGES, SHOP, xml, response, install_responses
from collectors.sitemap import SitemapCollector
from db.models import SCHEMA_SQL
from db.queries import apply_sitemap_snapshot


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "TEST_DATABASE_URL ontbreekt")
class SnapshotDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.dsn = os.environ["TEST_DATABASE_URL"]
        self.schema = "test_sitemap_" + uuid4().hex
        self.admin = psycopg2.connect(self.dsn)
        self.admin.autocommit = True
        with self.admin.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
            cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(self.schema)))
            cur.execute(SCHEMA_SQL)
            cur.execute("""
                INSERT INTO urls (shop_id, url, url_type, last_sitemap_seen, removed_from_sitemap)
                VALUES ('test', %s, 'product', '2020-01-01', FALSE),
                       ('test', %s, 'page', '2020-01-01', FALSE),
                       ('test', %s, 'product', '2020-01-01', TRUE),
                       ('other', %s, 'product', '2020-01-01', FALSE)
            """, (BASE + "/old-product", BASE + "/about", BASE + "/returned", BASE + "/other"))
        self.db_patch = patch("db.queries.get_connection", side_effect=self.connect)
        self.db_patch.start()

    def connect(self):
        return psycopg2.connect(self.dsn, options=f"-c search_path={self.schema}")

    def tearDown(self):
        self.db_patch.stop()
        with self.admin.cursor() as cur:
            cur.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))
        self.admin.close()

    def rows(self):
        with self.admin.cursor() as cur:
            cur.execute("SELECT * FROM urls ORDER BY shop_id, url")
            return cur.fetchall()

    def test_child_503_retains_existing_rows_then_recovery_detects_removals(self):
        before = self.rows()
        collector = SitemapCollector()
        responses = {
            ROOT: response(xml("sitemapindex", [PRODUCTS, PAGES])),
            PRODUCTS: response(status=503),
            PAGES: response(xml("urlset", [BASE + "/about", BASE + "/new-page"])),
        }
        install_responses(collector, responses)
        with self.assertLogs("collectors.sitemap", level="WARNING") as logs:
            result = collector.collect(SHOP)
        self.assertFalse(result.complete)
        self.assertIn("incompleet", " ".join(logs.output))
        self.assertEqual(self.rows(), before)

        responses[PRODUCTS] = response(xml("urlset", [BASE + "/returned", BASE + "/new-product"]))
        self.assertTrue(collector.collect(SHOP).complete)
        with self.admin.cursor() as cur:
            cur.execute("SELECT url, removed_from_sitemap FROM urls WHERE shop_id = 'test'")
            self.assertEqual(dict(cur.fetchall()), {
                BASE + "/old-product": True, BASE + "/about": False,
                BASE + "/returned": False, BASE + "/new-page": False,
                BASE + "/new-product": False,
            })
            cur.execute("SELECT removed_from_sitemap FROM urls WHERE shop_id = 'other'")
            self.assertEqual(cur.fetchone(), (False,))

    def test_empty_incomplete_snapshot_changes_nothing(self):
        before = self.rows()
        apply_sitemap_snapshot("test", [], complete=False)
        self.assertEqual(self.rows(), before)
        with self.assertRaises(ValueError):
            apply_sitemap_snapshot("test", [], complete=True)
        self.assertEqual(self.rows(), before)

    def test_database_failure_rolls_back_upserts_and_removals(self):
        before = self.rows()
        with self.admin.cursor() as cur:
            cur.execute("""
                CREATE FUNCTION reject_removal() RETURNS trigger AS $$
                BEGIN
                    IF NEW.removed_from_sitemap THEN
                        RAISE EXCEPTION 'simulated removal failure';
                    END IF;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
                CREATE TRIGGER reject_removal BEFORE UPDATE ON urls
                FOR EACH ROW EXECUTE FUNCTION reject_removal();
            """)
        with self.assertRaises(psycopg2.Error):
            apply_sitemap_snapshot("test", [(BASE + "/new-product", "product")], complete=True)
        self.assertEqual(self.rows(), before)

    def test_duplicates_across_batch_boundaries_merge_once(self):
        pairs = [(BASE + f"/p{i}", "product") for i in range(150)]
        apply_sitemap_snapshot("test", pairs + [(BASE + "/p0", None)], complete=True)
        with self.admin.cursor() as cur:
            cur.execute("SELECT count(*) FROM urls WHERE shop_id = 'test' AND NOT removed_from_sitemap")
            self.assertEqual(cur.fetchone(), (150,))
            cur.execute("SELECT url_type FROM urls WHERE shop_id = 'test' AND url = %s", (BASE + "/p0",))
            self.assertEqual(cur.fetchone(), ("product",))
