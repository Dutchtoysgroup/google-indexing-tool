"""Hoofdscript - wordt aangeroepen door GitHub Actions cron."""

import logging
import sys
import os
import time
from dataclasses import asdict

from pipeline_report import RunReport

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
                  optionele meldingen voor toegestane paginatypen en de monitoring
                  kunnen worden afgerond.
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

    shops = get_enabled_shops()
    report = RunReport(shops)
    logger.info(f"Runrapport: {report.path}")
    try:
        init_db()
    except Exception as exc:
        report.error("database_init", exc)
        logger.exception("Database initialisatie mislukt")
        return report.finish()

    logger.info(f"{len(shops)} shops geconfigureerd")

    def phase_error(shop, phase, exc):
        diagnostic = f"{type(exc).__name__}: {exc}"
        logger.error(f"[{shop.shop_id}] {phase} mislukt: {diagnostic}")
        report.phase(shop.shop_id, phase, "failed", error=diagnostic)

    # Scan failures must not stop the remaining shops or snapshots.
    logger.info("--- Stap 1: Sitemaps scannen ---")
    for shop in shops:
        if over_budget():
            report.phase(shop.shop_id, "scan", "skipped", reason="time_budget_exceeded")
            continue
        report.phase(shop.shop_id, "scan", "running")
        try:
            result = SitemapCollector().collect(shop)
        except Exception as exc:
            phase_error(shop, "scan", exc)
        else:
            report.phase(
                shop.shop_id, "scan",
                "success" if result.complete else "incomplete" if result.total else "failed",
                url_count=result.total, failed_sitemaps=result.failed_sitemaps, errors=result.errors,
            )

    logger.info("--- Stap 2: URLs inspecteren ---")
    inspector = None
    for shop in shops:
        if over_budget():
            report.phase(shop.shop_id, "inspect", "skipped", reason="time_budget_exceeded")
            continue
        report.phase(shop.shop_id, "inspect", "running")
        try:
            urls = get_inspection_urls(shop.shop_id)
            if urls:
                # Lazy auth: no scheduled work (including exhausted daily quota)
                # is a valid success and does not require an API connection.
                if inspector is None:
                    inspector = URLInspector()
                result = inspector.inspect_batch_result(
                    shop.shop_id, urls, shop.gsc_site_url, shop.language_code
                )
                details = asdict(result)
                status = result.status
            else:
                details = {"selected": 0, "attempted": 0, "succeeded": 0,
                           "skipped": 0, "errors": [], "reason": "no_scheduled_urls"}
                status = "success"
        except Exception as exc:
            phase_error(shop, "inspect", exc)
        else:
            report.phase(shop.shop_id, "inspect", status, **details)

    # Only eligible JobPosting/live video notifications; acceptance is not indexing. Always continue
    # to snapshots, even if authentication, scheduling or pushing raises.
    logger.info("--- Stap 3: Notificaties voor toegestane pagina’s ---")
    report.data["push"] = {"required": False, "status": "running", "batches": []}
    report.save()
    try:
        pusher = None
        for kind, select, method in (
            ("priority", get_priority_push_urls, "push_priority_batch"),
            ("regular", get_push_urls, "push_batch"),
        ):
            urls = select()
            accepted = 0
            outcomes = []
            if urls:
                if pusher is None:
                    pusher = IndexingPusher()
                accepted = getattr(pusher, method)(urls)
                outcomes = pusher.last_batch_outcomes
            report.data["push"]["batches"].append(
                {"kind": kind, "selected": len(urls), "notification_accepted": accepted, "outcomes": outcomes}
            )
            report.save()
    except Exception as exc:
        logger.warning(f"Indexing push mislukt: {exc}")
        report.data["push"].update(status="failed", error=f"{type(exc).__name__}: {exc}")
    else:
        batches = report.data["push"]["batches"]
        report.data["push"]["status"] = (
            "incomplete" if any(o["status"] in {"failed", "validation_failed", "unknown"} for b in batches for o in b["outcomes"]) else "success"
        )
    report.save()

    logger.info("--- Stap 4: Snapshots opslaan ---")
    for shop in shops:
        report.phase(shop.shop_id, "snapshot", "running")
        try:
            save_daily_snapshot(shop.shop_id)
        except Exception as exc:
            phase_error(shop, "snapshot", exc)
        else:
            report.phase(shop.shop_id, "snapshot", "success")

    # Eindrapport
    logger.info("--- Eindrapport ---")
    try:
        summaries = get_all_shops_summary()
    except Exception as exc:
        report.error("summary", exc)
        logger.exception("Eindrapport kon niet worden opgehaald")
        summaries = []
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
    exit_code = report.finish()
    for shop_id, outcome in report.data["shops"].items():
        logger.info(f"  {shop_id}: {outcome['status']}")
    log = logger.info if exit_code == 0 else logger.error
    log(f"Pipeline {report.data['status']} in {elapsed() / 60:.1f} min; rapport: {report.path}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
