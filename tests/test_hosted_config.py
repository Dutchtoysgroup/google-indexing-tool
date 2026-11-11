"""Gehoste omgeving: shops uit SHOPS_JSON en geen DDL op een beheerd schema."""

import json
import os
import unittest
from unittest.mock import patch

import tests.support  # noqa: F401  (laadt config.shops zonder shops.json)
import config.shops as shops
import db.models as models

SHOP = {
    "shop_id": "shop_nl", "name": "Shop NL", "base_url": "https://shop.example/",
    "gsc_site_url": "https://shop.example", "language_code": "nl-NL",
}


class ShopsFromEnvironmentTests(unittest.TestCase):
    def test_shops_json_wins_over_missing_file(self):
        with patch.dict(os.environ, {"SHOPS_JSON": json.dumps([SHOP])}), \
             patch("pathlib.Path.exists", return_value=False):
            loaded = shops._load_shops()
        self.assertEqual([s.shop_id for s in loaded], ["shop_nl"])
        self.assertEqual(loaded[0].base_url, "https://shop.example")
        self.assertEqual(loaded[0].gsc_site_url, "https://shop.example/")
        self.assertTrue(loaded[0].enabled)

    def test_invalid_shops_json_fails_clearly(self):
        for value in ["{niet json", json.dumps({"shop_id": "x"})]:
            with self.subTest(value=value), patch.dict(os.environ, {"SHOPS_JSON": value}):
                with self.assertRaisesRegex(RuntimeError, "SHOPS_JSON"):
                    shops._load_shops()

    def test_without_env_or_file_mentions_both_options(self):
        env = {k: v for k, v in os.environ.items() if k != "SHOPS_JSON"}
        with patch.dict(os.environ, env, clear=True), \
             patch("pathlib.Path.exists", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "SHOPS_JSON"):
                shops._load_shops()


class FakeCursor:
    def __init__(self, existing):
        self.existing = existing
        self.statements = []
        self.last = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, statement, params=None):
        self.statements.append(statement)
        self.last = params[0] if params else None

    def fetchone(self):
        return {"oid": self.last if self.last in self.existing else None}


class FakeConnection:
    def __init__(self, existing):
        self.cur = FakeCursor(existing)
        self.committed = self.closed = False

    def cursor(self):
        return self.cur

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


class ManagedSchemaTests(unittest.TestCase):
    def run_init(self, existing, auth):
        connection = FakeConnection(existing)
        env = {k: v for k, v in os.environ.items() if k != "DATABASE_AUTH"}
        if auth:
            env["DATABASE_AUTH"] = auth
        with patch.dict(os.environ, env, clear=True), \
             patch("db.models.get_connection", return_value=connection):
            try:
                models.init_db()
            finally:
                self.connection = connection
        return connection

    def test_entra_runs_no_ddl(self):
        connection = self.run_init(set(models.REQUIRED_TABLES), "entra")
        self.assertTrue(all("CREATE" not in s.upper() for s in connection.cur.statements))
        self.assertEqual(len(connection.cur.statements), len(models.REQUIRED_TABLES))
        self.assertTrue(connection.closed)

    def test_entra_reports_missing_table(self):
        existing = set(models.REQUIRED_TABLES) - {"indexing_requests"}
        with self.assertRaisesRegex(RuntimeError, "indexing_requests"):
            self.run_init(existing, "entra")
        self.assertTrue(self.connection.closed)

    def test_required_tables_exist_in_schema_sql(self):
        for table in models.REQUIRED_TABLES:
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table} (", models.SCHEMA_SQL)

    def test_self_managed_database_still_creates_schema(self):
        connection = self.run_init(set(), None)
        self.assertEqual(connection.cur.statements, [models.SCHEMA_SQL])
        self.assertTrue(connection.committed)


if __name__ == "__main__":
    unittest.main()
