"""Scheduling strategie - bepaalt welke URLs vandaag aan de beurt zijn."""

from __future__ import annotations

import logging

from config.settings import (
    INSPECTION_DAILY_LIMIT_PER_SHOP,
    INDEXING_DAILY_LIMIT,
    RETRY_INTERVAL_DAYS,
    RESCAN_INTERVAL_DAYS,
)
from db.queries import (
    get_urls_never_inspected,
    get_urls_needing_reinspection,
    get_urls_stale_inspection,
    get_urls_to_push,
    get_daily_api_usage,
    get_priority_urls_for_today,
)

logger = logging.getLogger(__name__)


def get_inspection_urls(shop_id: str) -> list[dict]:
    """Bepaal welke URLs vandaag geInspecteerd moeten worden voor deze shop.

    Prioriteit:
    1. Nieuwe URLs (nooit geInspecteerd)
    2. Gefaalde URLs (verdict != PASS, ouder dan 3 dagen)
    3. Verouderde inspections (ouder dan 7 dagen)
    """
    used = get_daily_api_usage("inspection", shop_id)
    budget = INSPECTION_DAILY_LIMIT_PER_SHOP - used
    if budget <= 0:
        logger.info(f"  {shop_id}: dagelijks limiet bereikt ({used} inspections)")
        return []

    urls: list[dict] = []

    # Prio 1: Nieuwe URLs
    new_urls = get_urls_never_inspected(shop_id, limit=budget)
    urls.extend(new_urls)
    budget -= len(new_urls)
    if new_urls:
        logger.info(f"  {shop_id}: {len(new_urls)} nieuwe URLs")

    # Prio 2: Gefaalde URLs opnieuw checken
    if budget > 0:
        retry_urls = get_urls_needing_reinspection(
            shop_id, days=RETRY_INTERVAL_DAYS, limit=budget
        )
        urls.extend(retry_urls)
        budget -= len(retry_urls)
        if retry_urls:
            logger.info(f"  {shop_id}: {len(retry_urls)} URLs voor retry")

    # Prio 3: Verouderde inspections
    if budget > 0:
        stale_urls = get_urls_stale_inspection(
            shop_id, days=RESCAN_INTERVAL_DAYS, limit=budget
        )
        urls.extend(stale_urls)
        if stale_urls:
            logger.info(f"  {shop_id}: {len(stale_urls)} verouderde URLs")

    return urls


def get_priority_push_urls(budget: int | None = None) -> list[dict]:
    """Pending priority URLs voor vandaag (en achterstallige van eerdere dagen).

    Deze URLs verbruiken het reguliere dagelijkse push-quotum (200/dag) en gaan
    voor in de wachtrij. Wanneer `budget` is opgegeven wordt de lijst beperkt
    tot dat aantal.
    """
    used = get_daily_api_usage("indexing")
    remaining = INDEXING_DAILY_LIMIT - used
    if remaining <= 0:
        return []

    cap = remaining if budget is None else min(remaining, budget)
    if cap <= 0:
        return []

    urls = get_priority_urls_for_today(limit=cap)
    if urls:
        logger.info(f"  {len(urls)} priority URLs geselecteerd om te pushen")
    return urls


def get_push_urls() -> list[dict]:
    """Bepaal welke URLs vandaag gepusht moeten worden.

    Respecteert het dagelijks limiet van 200 URLs totaal. Priority URLs zijn
    al apart afgehandeld door `get_priority_push_urls`, deze functie levert
    alleen de reguliere niet-geïndexeerde URLs.
    """
    used = get_daily_api_usage("indexing")
    budget = INDEXING_DAILY_LIMIT - used
    if budget <= 0:
        logger.info(f"Push limiet bereikt ({used}/{INDEXING_DAILY_LIMIT})")
        return []

    urls = get_urls_to_push(limit=budget)
    logger.info(f"  {len(urls)} URLs geselecteerd om te pushen")
    return urls
