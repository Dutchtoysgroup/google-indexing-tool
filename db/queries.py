"""Database query functies."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from db.models import get_connection


def upsert_url(shop_id: str, url: str, url_type: str | None = None):
    """Voeg URL toe of update last_sitemap_seen."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO urls (shop_id, url, url_type, last_sitemap_seen)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (shop_id, url)
                DO UPDATE SET
                    last_sitemap_seen = NOW(),
                    url_type = COALESCE(EXCLUDED.url_type, urls.url_type),
                    removed_from_sitemap = FALSE
            """, (shop_id, url, url_type))
        conn.commit()
    finally:
        conn.close()


def upsert_urls_batch(shop_id: str, urls: list[tuple[str, str | None]]):
    """Batch upsert van URLs. urls = [(url, url_type), ...]"""
    if not urls:
        return
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            from psycopg2.extras import execute_values
            execute_values(
                cur,
                """
                INSERT INTO urls (shop_id, url, url_type, last_sitemap_seen)
                VALUES %s
                ON CONFLICT (shop_id, url)
                DO UPDATE SET
                    last_sitemap_seen = NOW(),
                    url_type = COALESCE(EXCLUDED.url_type, urls.url_type),
                    removed_from_sitemap = FALSE
                """,
                [(shop_id, url, url_type, datetime.utcnow()) for url, url_type in urls],
                template="(%s, %s, %s, %s)",
            )
        conn.commit()
    finally:
        conn.close()


def mark_missing_urls(shop_id: str, current_urls: set[str]):
    """Markeer URLs die niet meer in de sitemap staan."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT url FROM urls WHERE shop_id = %s AND removed_from_sitemap = FALSE",
                (shop_id,),
            )
            db_urls = {row["url"] for row in cur.fetchall()}
            missing = db_urls - current_urls
            if missing:
                cur.execute(
                    """
                    UPDATE urls SET removed_from_sitemap = TRUE
                    WHERE shop_id = %s AND url = ANY(%s)
                    """,
                    (shop_id, list(missing)),
                )
        conn.commit()
    finally:
        conn.close()


def update_inspection_result(shop_id: str, url: str, result: dict):
    """Sla het URL Inspection API resultaat op."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE urls SET
                    coverage_state = %s,
                    verdict = %s,
                    robots_txt_state = %s,
                    indexing_state = %s,
                    last_crawl_time = %s,
                    last_inspected = NOW()
                WHERE shop_id = %s AND url = %s
            """, (
                result.get("coverage_state"),
                result.get("verdict"),
                result.get("robots_txt_state"),
                result.get("indexing_state"),
                result.get("last_crawl_time"),
                shop_id,
                url,
            ))
        conn.commit()
    finally:
        conn.close()


def mark_as_pushed(shop_id: str, url: str):
    """Registreer dat een URL is gepusht naar de Indexing API."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE urls SET
                    last_pushed = NOW(),
                    push_count = push_count + 1
                WHERE shop_id = %s AND url = %s
            """, (shop_id, url))
        conn.commit()
    finally:
        conn.close()


def get_urls_never_inspected(shop_id: str, limit: int = 100) -> list[dict]:
    """URLs die nog nooit zijn geInspecteerd."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT shop_id, url, url_type FROM urls
                WHERE shop_id = %s
                  AND last_inspected IS NULL
                  AND removed_from_sitemap = FALSE
                ORDER BY
                    CASE url_type
                        WHEN 'collection' THEN 1
                        WHEN 'product' THEN 2
                        WHEN 'page' THEN 3
                        WHEN 'blog' THEN 4
                        WHEN 'faq' THEN 5
                        ELSE 6
                    END
                LIMIT %s
            """, (shop_id, limit))
            return cur.fetchall()
    finally:
        conn.close()


def get_urls_needing_reinspection(shop_id: str, days: int = 3, limit: int = 100) -> list[dict]:
    """URLs met verdict != PASS die langer dan X dagen geleden zijn geInspecteerd."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT shop_id, url, url_type FROM urls
                WHERE shop_id = %s
                  AND verdict IS NOT NULL AND verdict != 'PASS'
                  AND last_inspected < %s
                  AND removed_from_sitemap = FALSE
                ORDER BY last_inspected ASC
                LIMIT %s
            """, (shop_id, cutoff, limit))
            return cur.fetchall()
    finally:
        conn.close()


def get_urls_stale_inspection(shop_id: str, days: int = 7, limit: int = 100) -> list[dict]:
    """URLs waarvan de inspection ouder is dan X dagen.

    PASS URLs worden pas na 30 dagen opnieuw gecheckt (lage prio).
    Niet-PASS URLs worden na `days` dagen opnieuw gecheckt.
    Niet-PASS URLs komen eerst aan de beurt.
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    cutoff_pass = datetime.utcnow() - timedelta(days=30)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT shop_id, url, url_type FROM urls
                WHERE shop_id = %s
                  AND last_inspected IS NOT NULL
                  AND removed_from_sitemap = FALSE
                  AND (
                    (verdict = 'PASS' AND last_inspected < %s)
                    OR
                    (verdict != 'PASS' AND last_inspected < %s)
                  )
                ORDER BY
                    CASE WHEN verdict = 'PASS' THEN 1 ELSE 0 END,
                    last_inspected ASC
                LIMIT %s
            """, (shop_id, cutoff_pass, cutoff, limit))
            return cur.fetchall()
    finally:
        conn.close()


def get_urls_to_push(limit: int = 200) -> list[dict]:
    """Niet-geIndexeerde URLs om te pushen, geprioriteerd."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT shop_id, url, url_type, coverage_state FROM urls
                WHERE verdict IS NOT NULL AND verdict != 'PASS'
                  AND removed_from_sitemap = FALSE
                  AND (last_pushed IS NULL OR last_pushed < NOW() - INTERVAL '3 days')
                ORDER BY
                    CASE url_type
                        WHEN 'collection' THEN 1
                        WHEN 'product' THEN 2
                        WHEN 'page' THEN 3
                        WHEN 'blog' THEN 4
                        WHEN 'faq' THEN 5
                        ELSE 6
                    END,
                    push_count ASC,
                    last_inspected DESC
                LIMIT %s
            """, (limit,))
            return cur.fetchall()
    finally:
        conn.close()


def get_daily_api_usage(api_type: str, shop_id: str | None = None) -> int:
    """Hoeveel API calls zijn er vandaag gedaan."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            if shop_id:
                cur.execute("""
                    SELECT COALESCE(SUM(url_count), 0) as total
                    FROM api_log WHERE date = CURRENT_DATE AND api_type = %s AND shop_id = %s
                """, (api_type, shop_id))
            else:
                cur.execute("""
                    SELECT COALESCE(SUM(url_count), 0) as total
                    FROM api_log WHERE date = CURRENT_DATE AND api_type = %s
                """, (api_type,))
            return cur.fetchone()["total"]
    finally:
        conn.close()


def log_api_usage(shop_id: str, api_type: str, url_count: int):
    """Registreer API usage."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO api_log (date, shop_id, api_type, url_count)
                VALUES (CURRENT_DATE, %s, %s, %s)
            """, (shop_id, api_type, url_count))
        conn.commit()
    finally:
        conn.close()


def save_daily_snapshot(shop_id: str):
    """Sla dagelijkse snapshot op voor trends."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE verdict = 'PASS') as indexed,
                    COUNT(*) FILTER (WHERE verdict IS NOT NULL AND verdict != 'PASS') as not_indexed,
                    COUNT(*) FILTER (WHERE verdict IS NULL) as unknown
                FROM urls
                WHERE shop_id = %s AND removed_from_sitemap = FALSE
            """, (shop_id,))
            stats = cur.fetchone()
            cur.execute("""
                INSERT INTO daily_snapshots (date, shop_id, total_urls, indexed_count, not_indexed_count, unknown_count)
                VALUES (CURRENT_DATE, %s, %s, %s, %s, %s)
                ON CONFLICT (date, shop_id)
                DO UPDATE SET
                    total_urls = EXCLUDED.total_urls,
                    indexed_count = EXCLUDED.indexed_count,
                    not_indexed_count = EXCLUDED.not_indexed_count,
                    unknown_count = EXCLUDED.unknown_count
            """, (shop_id, stats["total"], stats["indexed"], stats["not_indexed"], stats["unknown"]))
        conn.commit()
    finally:
        conn.close()


def get_shop_summary(shop_id: str) -> dict:
    """Haal samenvatting op per shop."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    COUNT(*) as total_urls,
                    COUNT(*) FILTER (WHERE verdict = 'PASS') as indexed,
                    COUNT(*) FILTER (WHERE verdict IS NOT NULL AND verdict != 'PASS') as not_indexed,
                    COUNT(*) FILTER (WHERE verdict IS NULL) as not_checked,
                    COUNT(*) FILTER (WHERE removed_from_sitemap = TRUE) as removed
                FROM urls WHERE shop_id = %s
            """, (shop_id,))
            return cur.fetchone()
    finally:
        conn.close()


def insert_priority_urls(
    rows: list[tuple[str, str | None]],
    source: str = "manual",
    daily_limit: int = 200,
    start_date: date | None = None,
) -> dict:
    """Plan priority URLs in voor toekomstige push-runs.

    Verdeelt URLs over opeenvolgende dagen wanneer het aantal het dagelijkse
    push-quotum overschrijdt. Eerst wordt de resterende ruimte voor vandaag
    benut (gebaseerd op reeds geplande priority URLs voor vandaag), daarna
    volgen volle dagen tot het lijstje op is.

    Args:
        rows: lijst van (url, shop_id) tuples. shop_id mag None zijn — wordt
              dan automatisch gedetecteerd uit het domein.
        source: vrije tag (bijv. 'manual', 'excel', 'dashboard').
        daily_limit: het maximum aantal priority URLs dat per dag mag worden
                     ingepland (en dus per dag wordt gepusht). Standaard 200,
                     gelijk aan Google's dagelijks push-quotum.
        start_date: optioneel startdatum (default: vandaag).

    Returns:
        Dict met aantal ingevoegde URLs en de spreiding over dagen.
    """
    if not rows:
        return {"inserted": 0, "skipped_duplicate": 0, "schedule": {}}

    if start_date is None:
        start_date = date.today()

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT scheduled_date, COUNT(*)::int AS cnt
                FROM priority_urls
                WHERE scheduled_date >= %s AND status = 'pending'
                GROUP BY scheduled_date
                """,
                (start_date,),
            )
            existing = {row["scheduled_date"]: row["cnt"] for row in cur.fetchall()}

            inserted = 0
            skipped = 0
            schedule: dict[str, int] = {}
            current_day = start_date

            for url, shop_id in rows:
                while existing.get(current_day, 0) >= daily_limit:
                    current_day = current_day + timedelta(days=1)

                try:
                    cur.execute(
                        """
                        INSERT INTO priority_urls
                            (url, shop_id, scheduled_date, source)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (url, scheduled_date) DO NOTHING
                        RETURNING id
                        """,
                        (url, shop_id, current_day, source),
                    )
                    result = cur.fetchone()
                    if result:
                        inserted += 1
                        existing[current_day] = existing.get(current_day, 0) + 1
                        day_key = current_day.isoformat()
                        schedule[day_key] = schedule.get(day_key, 0) + 1
                    else:
                        skipped += 1
                except Exception:
                    skipped += 1

        conn.commit()
        return {
            "inserted": inserted,
            "skipped_duplicate": skipped,
            "schedule": schedule,
        }
    finally:
        conn.close()


def get_priority_urls_for_today(limit: int | None = None) -> list[dict]:
    """Haal pending priority URLs op voor vandaag (inclusief achterstallige)."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            if limit is None:
                cur.execute(
                    """
                    SELECT id, url, shop_id, scheduled_date
                    FROM priority_urls
                    WHERE status = 'pending' AND scheduled_date <= CURRENT_DATE
                    ORDER BY scheduled_date ASC, id ASC
                    """
                )
            else:
                cur.execute(
                    """
                    SELECT id, url, shop_id, scheduled_date
                    FROM priority_urls
                    WHERE status = 'pending' AND scheduled_date <= CURRENT_DATE
                    ORDER BY scheduled_date ASC, id ASC
                    LIMIT %s
                    """,
                    (limit,),
                )
            return cur.fetchall()
    finally:
        conn.close()


def mark_priority_pushed(priority_id: int, success: bool, error: str | None = None):
    """Markeer een priority URL als gepusht (of failed)."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE priority_urls SET
                    status = %s,
                    push_error = %s,
                    pushed_at = NOW()
                WHERE id = %s
                """,
                ("pushed" if success else "failed", error, priority_id),
            )
        conn.commit()
    finally:
        conn.close()


def get_priority_schedule_summary(days_ahead: int = 30) -> list[dict]:
    """Aantal pending/pushed/failed priority URLs per dag, voor dashboard."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    scheduled_date::text AS scheduled_date,
                    COUNT(*) FILTER (WHERE status = 'pending')::int  AS pending,
                    COUNT(*) FILTER (WHERE status = 'pushed')::int   AS pushed,
                    COUNT(*) FILTER (WHERE status = 'failed')::int   AS failed
                FROM priority_urls
                WHERE scheduled_date >= CURRENT_DATE - INTERVAL '7 days'
                  AND scheduled_date <= CURRENT_DATE + make_interval(days => %s)
                GROUP BY scheduled_date
                ORDER BY scheduled_date ASC
                """,
                (days_ahead,),
            )
            return cur.fetchall()
    finally:
        conn.close()


def get_priority_urls_for_date(scheduled_date: date, status: str | None = None) -> list[dict]:
    """Alle priority URLs voor een specifieke datum, optioneel gefilterd op status."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            if status:
                cur.execute(
                    """
                    SELECT id, url, shop_id, scheduled_date::text, status,
                           pushed_at::text, push_error, source, created_at::text
                    FROM priority_urls
                    WHERE scheduled_date = %s AND status = %s
                    ORDER BY id ASC
                    """,
                    (scheduled_date, status),
                )
            else:
                cur.execute(
                    """
                    SELECT id, url, shop_id, scheduled_date::text, status,
                           pushed_at::text, push_error, source, created_at::text
                    FROM priority_urls
                    WHERE scheduled_date = %s
                    ORDER BY id ASC
                    """,
                    (scheduled_date,),
                )
            return cur.fetchall()
    finally:
        conn.close()


def delete_priority_url(priority_id: int) -> bool:
    """Verwijder een priority URL (alleen als pending)."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM priority_urls WHERE id = %s AND status = 'pending'",
                (priority_id,),
            )
            deleted = cur.rowcount > 0
        conn.commit()
        return deleted
    finally:
        conn.close()


def get_all_shops_summary() -> list[dict]:
    """Haal samenvatting op voor alle shops."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    shop_id,
                    COUNT(*) as total_urls,
                    COUNT(*) FILTER (WHERE verdict = 'PASS') as indexed,
                    COUNT(*) FILTER (WHERE verdict IS NOT NULL AND verdict != 'PASS') as not_indexed,
                    COUNT(*) FILTER (WHERE verdict IS NULL) as not_checked
                FROM urls
                WHERE removed_from_sitemap = FALSE
                GROUP BY shop_id
                ORDER BY shop_id
            """)
            return cur.fetchall()
    finally:
        conn.close()
