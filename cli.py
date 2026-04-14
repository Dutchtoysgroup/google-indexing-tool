"""CLI interface voor de EXIT Toys Indexing Tool."""

import logging
import sys

import click

from config.shops import get_enabled_shops, get_shop_by_id
from db.models import init_db
from db.queries import get_all_shops_summary, get_shop_summary, get_daily_api_usage, save_daily_snapshot
from collectors.sitemap import SitemapCollector
from inspectors.url_inspector import URLInspector
from pushers.indexing_pusher import IndexingPusher
from scheduler.strategy import get_inspection_urls, get_push_urls


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Verbose logging")
def cli(verbose):
    """EXIT Toys Google Indexing Tool"""
    setup_logging(verbose)
    init_db()


@cli.command()
@click.option("--shop", "-s", default=None, help="Shop ID (bijv. exittoys_nl)")
def scan(shop):
    """Verzamel URLs uit sitemaps van alle (of een specifieke) shop."""
    collector = SitemapCollector()

    if shop:
        shop_obj = get_shop_by_id(shop)
        if not shop_obj:
            click.echo(f"Shop '{shop}' niet gevonden.")
            sys.exit(1)
        shops = [shop_obj]
    else:
        shops = get_enabled_shops()

    total = 0
    for s in shops:
        urls = collector.collect(s)
        count = sum(len(v) for v in urls.values())
        total += count
        click.echo(f"  {s.name}: {count} URLs")

    click.echo(f"\nTotaal: {total} URLs verzameld uit {len(shops)} shops")


@cli.command()
@click.option("--shop", "-s", default=None, help="Shop ID")
@click.option("--limit", "-l", default=None, type=int, help="Max URLs per shop")
def inspect(shop, limit):
    """Check indexeringsstatus via URL Inspection API."""
    inspector = URLInspector()

    if shop:
        shop_obj = get_shop_by_id(shop)
        if not shop_obj:
            click.echo(f"Shop '{shop}' niet gevonden.")
            sys.exit(1)
        shops = [shop_obj]
    else:
        shops = get_enabled_shops()

    total = 0
    for s in shops:
        click.echo(f"\nInspecteren: {s.name}")
        urls = get_inspection_urls(s.shop_id)
        if limit:
            urls = urls[:limit]

        if not urls:
            click.echo("  Geen URLs om te inspecteren")
            continue

        click.echo(f"  {len(urls)} URLs geselecteerd")
        count = inspector.inspect_batch(s.shop_id, urls, s.gsc_site_url, s.language_code)
        total += count
        click.echo(f"  {count} URLs succesvol geInspecteerd")

    click.echo(f"\nTotaal: {total} URLs geInspecteerd")


@cli.command()
@click.option("--shop", "-s", default=None, help="Shop ID (filter)")
@click.option("--limit", "-l", default=None, type=int, help="Max URLs om te pushen")
def push(shop, limit):
    """Push niet-geIndexeerde URLs via de Indexing API."""
    pusher = IndexingPusher()
    urls = get_push_urls()

    if shop:
        urls = [u for u in urls if u["shop_id"] == shop]

    if limit:
        urls = urls[:limit]

    if not urls:
        click.echo("Geen URLs om te pushen.")
        return

    click.echo(f"{len(urls)} URLs worden gepusht...")
    count = pusher.push_batch(urls)
    click.echo(f"\n{count} URLs succesvol gepusht")


@cli.command()
@click.option("--shop", "-s", default=None, help="Shop ID")
def report(shop):
    """Toon een statusrapport."""
    if shop:
        shop_obj = get_shop_by_id(shop)
        if not shop_obj:
            click.echo(f"Shop '{shop}' niet gevonden.")
            sys.exit(1)
        stats = get_shop_summary(shop)
        click.echo(f"\n{'=' * 60}")
        click.echo(f"  {shop_obj.name} ({shop_obj.base_url})")
        click.echo(f"{'=' * 60}")
        click.echo(f"  Totaal URLs:     {stats['total_urls']}")
        click.echo(f"  GeIndexeerd:     {stats['indexed']}")
        click.echo(f"  Niet geIndexeerd:{stats['not_indexed']}")
        click.echo(f"  Niet gecheckt:   {stats['not_checked']}")
        click.echo(f"  Verwijderd:      {stats['removed']}")
        if stats['total_urls'] > 0:
            pct = (stats['indexed'] / stats['total_urls']) * 100
            click.echo(f"  Coverage:        {pct:.1f}%")
    else:
        summaries = get_all_shops_summary()
        if not summaries:
            click.echo("Geen data beschikbaar. Voer eerst 'scan' en 'inspect' uit.")
            return

        click.echo(f"\n{'Shop':<20} {'Totaal':>8} {'Indexed':>8} {'Not OK':>8} {'Unknown':>8} {'Coverage':>10}")
        click.echo("-" * 72)

        grand_total = grand_indexed = grand_not = grand_unknown = 0
        for s in summaries:
            total = s["total_urls"]
            indexed = s["indexed"]
            not_idx = s["not_indexed"]
            unknown = s["not_checked"]
            pct = f"{(indexed / total * 100):.1f}%" if total > 0 else "N/A"

            click.echo(f"{s['shop_id']:<20} {total:>8} {indexed:>8} {not_idx:>8} {unknown:>8} {pct:>10}")

            grand_total += total
            grand_indexed += indexed
            grand_not += not_idx
            grand_unknown += unknown

        click.echo("-" * 72)
        grand_pct = f"{(grand_indexed / grand_total * 100):.1f}%" if grand_total > 0 else "N/A"
        click.echo(f"{'TOTAAL':<20} {grand_total:>8} {grand_indexed:>8} {grand_not:>8} {grand_unknown:>8} {grand_pct:>10}")


@cli.command()
def status():
    """Toon API usage van vandaag."""
    click.echo("\nAPI Usage vandaag:")
    click.echo("-" * 40)

    shops = get_enabled_shops()
    for s in shops:
        inspections = get_daily_api_usage("inspection", s.shop_id)
        pushes = get_daily_api_usage("indexing", s.shop_id)
        if inspections > 0 or pushes > 0:
            click.echo(f"  {s.shop_id}: {inspections} inspections, {pushes} pushes")

    total_inspections = get_daily_api_usage("inspection")
    total_pushes = get_daily_api_usage("indexing")
    click.echo(f"\n  Totaal: {total_inspections} inspections, {total_pushes} pushes")


@cli.command()
def run():
    """Voer de volledige pipeline uit: scan -> inspect -> push -> snapshot."""
    logger = logging.getLogger("pipeline")

    # Stap 1: Scan sitemaps
    logger.info("=== STAP 1: Sitemaps scannen ===")
    collector = SitemapCollector()
    for s in get_enabled_shops():
        collector.collect(s)

    # Stap 2: Inspecteer URLs
    logger.info("=== STAP 2: URLs inspecteren ===")
    inspector = URLInspector()
    for s in get_enabled_shops():
        urls = get_inspection_urls(s.shop_id)
        if urls:
            inspector.inspect_batch(s.shop_id, urls, s.gsc_site_url, s.language_code)

    # Stap 3: Push niet-geIndexeerde URLs
    logger.info("=== STAP 3: URLs pushen ===")
    pusher = IndexingPusher()
    push_urls = get_push_urls()
    if push_urls:
        pusher.push_batch(push_urls)

    # Stap 4: Dagelijkse snapshot opslaan
    logger.info("=== STAP 4: Snapshots opslaan ===")
    for s in get_enabled_shops():
        save_daily_snapshot(s.shop_id)

    # Rapport
    logger.info("=== RAPPORT ===")
    summaries = get_all_shops_summary()
    for s in summaries:
        total = s["total_urls"]
        indexed = s["indexed"]
        pct = f"{(indexed / total * 100):.1f}%" if total > 0 else "N/A"
        logger.info(f"  {s['shop_id']}: {total} URLs, {indexed} indexed ({pct})")

    logger.info("Pipeline voltooid.")


if __name__ == "__main__":
    cli()
