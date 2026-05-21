"""Webshop configuratie - leest shops.json in.

De daadwerkelijke webshop-data staat in `config/shops.json` (gitignored zodat
elke gebruiker zijn eigen webshops kan invullen). Een sjabloon staat in
`config/shops.example.json`. Kopieer dat bestand naar `shops.json` en pas het
aan voordat je de tool draait.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


CONFIG_DIR = Path(__file__).parent
SHOPS_FILE = CONFIG_DIR / "shops.json"
EXAMPLE_FILE = CONFIG_DIR / "shops.example.json"


@dataclass
class Shop:
    shop_id: str
    name: str
    base_url: str
    gsc_site_url: str
    language_code: str
    enabled: bool = True


def _load_shops() -> list[Shop]:
    if not SHOPS_FILE.exists():
        raise RuntimeError(
            f"Configuratiebestand niet gevonden: {SHOPS_FILE}\n"
            f"Kopieer {EXAMPLE_FILE.name} naar shops.json en vul je eigen "
            f"webshops in. Zie de README voor uitleg."
        )

    with SHOPS_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise RuntimeError(
            f"{SHOPS_FILE} moet een JSON-lijst zijn met webshop-objecten."
        )

    shops: list[Shop] = []
    for entry in data:
        # base_url zonder trailing slash, gsc_site_url juist mét trailing slash
        # (zoals Google Search Console het verwacht voor URL-property's).
        base_url = entry["base_url"].rstrip("/")
        gsc_site_url = entry["gsc_site_url"]
        if not gsc_site_url.endswith("/") and "://" in gsc_site_url:
            gsc_site_url = gsc_site_url + "/"

        shops.append(
            Shop(
                shop_id=entry["shop_id"],
                name=entry["name"],
                base_url=base_url,
                gsc_site_url=gsc_site_url,
                language_code=entry["language_code"],
                enabled=entry.get("enabled", True),
            )
        )
    return shops


SHOPS: list[Shop] = _load_shops()


def get_enabled_shops() -> list[Shop]:
    return [s for s in SHOPS if s.enabled]


def get_shop_by_id(shop_id: str) -> Shop | None:
    return next((s for s in SHOPS if s.shop_id == shop_id), None)


def get_shop_for_url(url: str) -> Shop | None:
    """Vind de shop waar deze URL bij hoort op basis van het domein."""
    if not url or "://" not in url:
        return None
    # Pak alleen de host (zonder pad/query).
    try:
        host = url.split("://", 1)[1].split("/", 1)[0].lower()
    except IndexError:
        return None
    # Eerst exact match op host vs base_url's host.
    for shop in SHOPS:
        base_host = shop.base_url.split("://", 1)[1].split("/", 1)[0].lower()
        if host == base_host:
            return shop
    # Anders: substring match (bv. URL heeft 'www.', shop niet).
    for shop in SHOPS:
        base_host = shop.base_url.split("://", 1)[1].split("/", 1)[0].lower()
        if host.endswith(base_host) or base_host.endswith(host):
            return shop
    return None
