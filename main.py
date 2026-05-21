"""Hoofdscript - wordt aangeroepen door GitHub Actions cron."""

import logging
import sys
import os
import time

# Voeg project root toe aan sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.shops import get_enabled_shops
from db.models import init_db
from db.queries import save_daily_snapshot, get_all_shops_summary
from collectors.sitemap import SitemapCollector
from inspectors.url_inspector import URLInspector
from pushers.indexing_pusher import IndexingPusher
from scheduler.strategy import get_inspection_urls, get_push_urls, get_priority_push_urls


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def get_time_budget_seconds():
    """Leest TIME_BUDGET_MINUTES env var.

    - Niet gezet → None (geen limiet; Mac Mini / lokaal draait alles).
    - Gezet     → geldt voor stap 1 (scan) + stap 2 (inspect) samen. Stap 3
                  (push) en stap 4 (snapshot) lopen altijd door, zodat het
                  Google-indexeringsbudget (200/dag) ook daadwerkelijk benut
                  wordt op GitHub Actions waar runtime beperkt is.
    """
    raw = os.environ.get("TIME_BUDGET_MINUTES")
    if not raw:
        return None
    try:
        minutes = float(raw)
    except ValueError:
        return None
    if minutes <= 0:
        return None
    return minutes * 60.0


def main():
    setup_logging()
    logger = logging.getLogger("main")
    logger.info("Indexing pipeline gestart")

    budget_seconds = get_time_budget_seconds()
    start_time = time.monotonic()

    def elapsed():
        return time.monotonic() - start_time

    def over_budget():
        return budget_seconds is not None and elapsed() >= budget_seconds

    if budget_seconds is not None:
        logger.info(
            f"Tijdsbudget actief: {budget_seconds / 60:.0f} min voor scan+inspect "
            f"(push en snapshot lopen altijd door)"
        )
    else:
        logger.info("Geen tijdsbudget — draait tot klaar")

    # Database initialiseren
    init_db()

    shops = get_enabled_shops()
    logger.info(f"{len(shops)} shops geconfigureerd")

    # Stap 1: Sitemaps scannen
    logger.info("--- Stap 1: Sitemaps scannen ---")
    collector = SitemapCollector()
    for shop in shops:
        if over_budget():
            logger.warning(
                f"Tijdsbudget verstreken na {elapsed() / 60:.1f} min — "
                f"scan afgebroken; resterende shops worden overgeslagen"
            )
            break
        try:
            collector.collect(shop)
        except Exception as e:
            logger.error(f"Fout bij scannen {shop.name}: {e}")

    # Stap 2: URLs inspecteren
    logger.info("--- Stap 2: URLs inspecteren ---")
    if over_budget():
        logger.warning(
            f"Tijdsbudget al verstreken ({elapsed() / 60:.1f} min) — "
            f"inspecties overgeslagen; direct door naar push"
        )
    else:
        try:
            inspector = URLInspector()
            for shop in shops:
                if over_budget():
                    logger.warning(
                        f"Tijdsbudget verstreken na {elapsed() / 60:.1f} min — "
                        f"resterende shops inspecties overslaan"
                    )
                    break
                try:
                    urls = get_inspection_urls(shop.shop_id)
                    if urls:
                        logger.info(
                            f"  {shop.shop_id}: {len(urls)} URLs te inspecteren"
                        )
                        inspector.inspect_batch(
                            shop.shop_id, urls, shop.gsc_site_url, shop.language_code
                        )
                except Exception as e:
                    logger.error(f"Fout bij inspecteren {shop.name}: {e}")
        except RuntimeError as e:
            logger.warning(f"URL Inspection overgeslagen: {e}")

    # Stap 3: Niet-geIndexeerde URLs pushen (geen budget-check: altijd door)
    logger.info(
        f"--- Stap 3: URLs pushen --- (elapsed: {elapsed() / 60:.1f} min)"
    )
    try:
        pusher = IndexingPusher()

        # Stap 3a: priority URLs (handmatig versneld). Verbruikt hetzelfde
        # dagelijkse quotum maar gaat voor in de wachtrij.
        priority_urls = get_priority_push_urls()
        if priority_urls:
            logger.info(f"  Priority queue: {len(priority_urls)} URLs")
            pusher.push_priority_batch(priority_urls)
        else:
            logger.info("  Geen priority URLs in de wachtrij")

        # Stap 3b: reguliere niet-geïndexeerde URLs.
        push_urls = get_push_urls()
        if push_urls:
            logger.info(f"  {len(push_urls)} URLs te pushen")
            pusher.push_batch(push_urls)
        else:
            logger.info("  Geen URLs om te pushen")
    except RuntimeError as e:
        logger.warning(f"Indexing push overgeslagen: {e}")

    # Stap 4: Dagelijkse snapshots (altijd door)
    logger.info("--- Stap 4: Snapshots opslaan ---")
    for shop in shops:
        try:
            save_daily_snapshot(shop.shop_id)
        except Exception as e:
            logger.error(f"Fout bij snapshot {shop.name}: {e}")

    # Eindrapport
    logger.info("--- Eindrapport ---")
    summaries = get_all_shops_summary()
    total_all = indexed_all = 0
    for s in summaries:
        total = s["total_urls"]
        indexed = s["indexed"]
        total_all += total
        indexed_all += indexed
        pct = f"{(indexed / total * 100):.1f}%" if total > 0 else "N/A"
        logger.info(f"  {s['shop_id']}: {total} URLs, {indexed} indexed ({pct})")

    overall_pct = f"{(indexed_all / total_all * 100):.1f}%" if total_all > 0 else "N/A"
    logger.info(f"  TOTAAL: {total_all} URLs, {indexed_all} indexed ({overall_pct})")
    logger.info(f"Pipeline voltooid in {elapsed() / 60:.1f} min.")


if __name__ == "__main__":
    main()
