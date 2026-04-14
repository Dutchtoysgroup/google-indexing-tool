"""Configuratie van alle EXIT Toys webshops."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Shop:
    shop_id: str
    name: str
    base_url: str
    gsc_site_url: str
    language_code: str
    enabled: bool = True


SHOPS: list[Shop] = [
    Shop(
        shop_id="exittoys_nl",
        name="EXIT Toys Nederland",
        base_url="https://www.exittoys.nl",
        gsc_site_url="https://www.exittoys.nl/",
        language_code="nl-NL",
    ),
    Shop(
        shop_id="exittoys_be",
        name="EXIT Toys België",
        base_url="https://www.exittoys.be",
        gsc_site_url="https://www.exittoys.be/",
        language_code="nl-BE",
    ),
    Shop(
        shop_id="exittoys_de",
        name="EXIT Toys Deutschland",
        base_url="https://www.exittoys.de",
        gsc_site_url="https://www.exittoys.de/",
        language_code="de-DE",
    ),
    Shop(
        shop_id="exittoys_at",
        name="EXIT Toys Österreich",
        base_url="https://www.exittoys.at",
        gsc_site_url="https://www.exittoys.at/",
        language_code="de-AT",
    ),
    Shop(
        shop_id="exittoys_uk",
        name="EXIT Toys United Kingdom",
        base_url="https://www.exittoys.co.uk",
        gsc_site_url="https://www.exittoys.co.uk/",
        language_code="en-GB",
    ),
    Shop(
        shop_id="exittoys_ie",
        name="EXIT Toys Ireland",
        base_url="https://www.exittoys.ie",
        gsc_site_url="https://www.exittoys.ie/",
        language_code="en-IE",
    ),
    Shop(
        shop_id="exittoys_se",
        name="EXIT Toys Sverige",
        base_url="https://www.exittoys.se",
        gsc_site_url="https://www.exittoys.se/",
        language_code="sv-SE",
    ),
    Shop(
        shop_id="exittoys_dk",
        name="EXIT Toys Danmark",
        base_url="https://www.exittoys.dk",
        gsc_site_url="https://www.exittoys.dk/",
        language_code="da-DK",
    ),
    Shop(
        shop_id="exittoys_es",
        name="EXIT Toys España",
        base_url="https://www.exittoys.es",
        gsc_site_url="https://www.exittoys.es/",
        language_code="es-ES",
    ),
    Shop(
        shop_id="exittoys_it",
        name="EXIT Toys Italia",
        base_url="https://www.exittoys.it",
        gsc_site_url="https://www.exittoys.it/",
        language_code="it-IT",
    ),
    Shop(
        shop_id="exittoys_pl",
        name="EXIT Toys Polska",
        base_url="https://www.exittoys.pl",
        gsc_site_url="https://www.exittoys.pl/",
        language_code="pl-PL",
    ),
    Shop(
        shop_id="exittoys_fr",
        name="EXIT Toys France",
        base_url="https://www.exittoys.fr",
        gsc_site_url="https://www.exittoys.fr/",
        language_code="fr-FR",
    ),
]


def get_enabled_shops() -> list[Shop]:
    return [s for s in SHOPS if s.enabled]


def get_shop_by_id(shop_id: str) -> Shop | None:
    return next((s for s in SHOPS if s.shop_id == shop_id), None)
