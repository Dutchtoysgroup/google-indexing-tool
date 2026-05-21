"""Database schema en connectie voor Neon PostgreSQL."""

import psycopg2
from psycopg2.extras import RealDictCursor

from config.settings import DATABASE_URL

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS urls (
    id SERIAL PRIMARY KEY,
    shop_id TEXT NOT NULL,
    url TEXT NOT NULL,
    url_type TEXT,
    coverage_state TEXT,
    verdict TEXT,
    robots_txt_state TEXT,
    indexing_state TEXT,
    last_crawl_time TIMESTAMP,
    last_inspected TIMESTAMP,
    last_pushed TIMESTAMP,
    push_count INT DEFAULT 0,
    first_seen TIMESTAMP DEFAULT NOW(),
    last_sitemap_seen TIMESTAMP,
    removed_from_sitemap BOOLEAN DEFAULT FALSE,
    UNIQUE(shop_id, url)
);

CREATE INDEX IF NOT EXISTS idx_urls_shop_verdict ON urls(shop_id, verdict);
CREATE INDEX IF NOT EXISTS idx_urls_coverage ON urls(coverage_state);
CREATE INDEX IF NOT EXISTS idx_urls_last_inspected ON urls(last_inspected);

CREATE TABLE IF NOT EXISTS api_log (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    shop_id TEXT NOT NULL,
    api_type TEXT NOT NULL,
    url_count INT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_log_date ON api_log(date, api_type, shop_id);

CREATE TABLE IF NOT EXISTS daily_snapshots (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    shop_id TEXT NOT NULL,
    total_urls INT DEFAULT 0,
    indexed_count INT DEFAULT 0,
    not_indexed_count INT DEFAULT 0,
    unknown_count INT DEFAULT 0,
    UNIQUE(date, shop_id)
);

CREATE TABLE IF NOT EXISTS priority_urls (
    id SERIAL PRIMARY KEY,
    url TEXT NOT NULL,
    shop_id TEXT,
    scheduled_date DATE NOT NULL DEFAULT CURRENT_DATE,
    status TEXT NOT NULL DEFAULT 'pending',
    push_error TEXT,
    pushed_at TIMESTAMP,
    source TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(url, scheduled_date)
);

CREATE INDEX IF NOT EXISTS idx_priority_urls_date_status
    ON priority_urls(scheduled_date, status);
"""


def get_connection():
    """Maak een database connectie."""
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is niet geconfigureerd")
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def init_db():
    """Maak alle tabellen aan als ze niet bestaan."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()
