"""Hoofdscript - wordt aangeroepen door GitHub Actions cron."""

import logging
import sys
import os

# Voeg project root toe aan sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.shops import get_enabled_shops
from db.models import init_db
from db.queries import save_daily_snapshot, get_all_shops_summary
from collectors.sitemap import SitemapCollector
from inspectors.url_inspector import URLInspector
from pushers.indexing_pusher import IndexingPusher
from scheduler.strategy import get_inspection_urls, get_push_urls


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main():
    setup_logging()
    logger = logging.getLogger("main")
    logger.info("EXIT Toys Indexing Pipeline gestart")

    # Database initialiseren
    init_db()

    shops = get_enabled_shops()
    logger.info(f"{len(shops)} shops geconfigureerd")

    # Stap 1: Sitemaps scannen
    logger.info("--- Stap 1: Sitemaps scannen ---")
    collector = SitemapCollector()
    for shop in shops:
        try:
            collector.collect(shop)
        except Exception as e:
            logger.error(f"Fout bij scannen {shop.name}: {e}")

    # Stap 2: URLs inspecteren
    logger.info("--- Stap 2: URLs inspecteren ---")
    try:
        inspector = URLInspector()
        for shop in shops:
            try:
                urls = get_inspection_urls(shop.shop_id)
                if urls:
                    logger.info(f"  {shop.shop_id}: {len(urls)} URLs te inspecteren")
                    inspector.inspect_batch(
                        shop.shop_id, urls, shop.gsc_site_url, shop.language_code
                    )
            except Exception as e:
                logger.error(f"Fout bij inspecteren {shop.name}: {e}")
    except RuntimeError as e:
        logger.warning(f"URL Inspection overgeslagen: {e}")

    # Stap 3: Niet-geIndexeerde URLs pushen
    logger.info("--- Stap 3: URLs pushen ---")
    try:
        pusher = IndexingPusher()
        push_urls = get_push_urls()
        if push_urls:
            logger.info(f"  {len(push_urls)} URLs te pushen")
            pusher.push_batch(push_urls)
        else:
            logger.info("  Geen URLs om te pushen")
    except RuntimeError as e:
        logger.warning(f"Indexing push overgeslagen: {e}")

    # Stap 4: Dagelijkse snapshots
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
    logger.info("Pipeline voltooid.")


if __name__ == "__main__":
    main()
