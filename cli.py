"""CLI interface voor de Google Indexing Tool."""

import logging
import sys

import click

from config.shops import get_enabled_shops, get_shop_by_id
from db.models import init_db
from db.queries import (
    get_all_shops_summary,
    get_shop_summary,
    get_daily_api_usage,
    save_daily_snapshot,
    get_priority_schedule_summary,
)
from collectors.sitemap import SitemapCollector
from inspectors.url_inspector import URLInspector
from pushers.indexing_pusher import IndexingPusher
from scheduler.strategy import get_inspection_urls, get_push_urls, get_priority_push_urls
from scheduler.priority import parse_file, parse_text, schedule_priority_urls


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
    """Google Indexing Tool — monitor en push URLs naar de Google Indexing API."""
    setup_logging(verbose)
    init_db()


@cli.command()
@click.option("--shop", "-s", default=None, help="Shop ID zoals in shops.json")
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


@cli.group()
def priority():
    """Beheer priority URLs: handmatig versneld indexeren."""
    pass


@priority.command("add")
@click.option(
    "--file",
    "-f",
    "file_path",
    type=click.Path(exists=True, dir_okay=False),
    help="Pad naar een .txt / .csv / .xlsx bestand met URLs.",
)
@click.option(
    "--urls",
    "-u",
    "urls_arg",
    default=None,
    help="Direct opgegeven URLs (comma-separated of newline-separated).",
)
@click.option(
    "--source",
    "-s",
    default="cli",
    help="Tag waarmee deze batch is opgenomen (default: cli).",
)
def priority_add(file_path, urls_arg, source):
    """Voeg URLs toe aan de priority push-wachtrij.

    Voorbeelden:
        python cli.py priority add -f exit_blog_urls.xlsx
        python cli.py priority add -u "https://shop.nl/a, https://shop.nl/b"
    """
    if not file_path and not urls_arg:
        click.echo("Geef minstens --file of --urls op.")
        sys.exit(1)

    urls: list[str] = []
    if file_path:
        urls.extend(parse_file(file_path))
    if urls_arg:
        urls.extend(parse_text(urls_arg))

    if not urls:
        click.echo("Geen geldige URLs gevonden in de input.")
        sys.exit(1)

    result = schedule_priority_urls(urls, source=source)
    click.echo(f"\nIngepland: {result['inserted']} URLs")
    click.echo(f"  Aangeboden:        {result['received']}")
    click.echo(f"  Na dedup:          {result['deduped']}")
    click.echo(f"  Duplicaat in db:   {result['skipped_duplicate']}")
    click.echo(f"  Zonder shop-match: {result['unmapped']}")
    if result["unmapped_sample"]:
        click.echo("  Voorbeeld(en) zonder shop-match:")
        for sample in result["unmapped_sample"]:
            click.echo(f"    - {sample}")
    if result["schedule"]:
        click.echo("\nVerdeling over dagen:")
        for day, count in sorted(result["schedule"].items()):
            click.echo(f"  {day}: {count}")


@priority.command("list")
@click.option("--days", "-d", default=14, type=int, help="Aantal dagen vooruit (default: 14).")
def priority_list(days):
    """Toon geplande priority pushes per dag."""
    summary = get_priority_schedule_summary(days_ahead=days)
    if not summary:
        click.echo("Geen priority URLs gepland.")
        return
    click.echo(f"\n{'Datum':<12} {'Pending':>8} {'Pushed':>8} {'Failed':>8}")
    click.echo("-" * 40)
    for row in summary:
        click.echo(
            f"{row['scheduled_date']:<12} {row['pending']:>8} {row['pushed']:>8} {row['failed']:>8}"
        )


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

    # Stap 3: Push niet-geIndexeerde URLs (priority eerst, dan regulier)
    logger.info("=== STAP 3: URLs pushen ===")
    pusher = IndexingPusher()

    priority_urls = get_priority_push_urls()
    if priority_urls:
        logger.info(f"  Priority queue: {len(priority_urls)} URLs")
        pusher.push_priority_batch(priority_urls)

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
