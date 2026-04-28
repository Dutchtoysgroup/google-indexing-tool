# Hoe werkt de pipeline?

Dit document beschrijft in detail wat er bij elke run van de tool gebeurt, hoe je hem monitort en hoe je hem aanpast voor je eigen situatie.

Voor de installatie verwijzen we naar [`README.md`](README.md). Dit document gaat over wat er *daarna* onder water gebeurt.

---

## Overzicht

```
Per run (bijvoorbeeld dagelijks):

  STAP 1: SCAN          STAP 2: INSPECT         STAP 3: PUSH           STAP 4: SNAPSHOT
  ┌─────────────────┐   ┌───────────────────┐   ┌───────────────────┐   ┌──────────────────┐
  │ Sitemaps        │   │ Google URL        │   │ Google Indexing   │   │ Statistieken     │
  │ ophalen voor    │──▶│ Inspection API    │──▶│ API aanroepen     │──▶│ opslaan voor     │
  │ alle shops      │   │ status per URL    │   │ voor failed URLs  │   │ trends/dashboard │
  └─────────────────┘   └───────────────────┘   └───────────────────┘   └──────────────────┘
        │                       │                       │                       │
   alle URLs              max 2.000/shop/dag       max 200/dag             1 snapshot
   in database            Status per URL            prioriteit:            per shop
                          PASS / NEUTRAL / FAIL     collections eerst      per dag
```

---

## Stap 1: Sitemap-scan

**Wat gebeurt er?**
- Voor elke shop in `config/shops.json` haalt de tool de root-sitemap op (`<base_url>/sitemap.xml`).
- Deze root is meestal een sitemap-index die verwijst naar deelsitemaps:
  - `sitemap-products.xml`
  - `sitemap-collections.xml` of `sitemap-categories.xml`
  - `sitemap-pages.xml`
  - `sitemap-faqs.xml`
  - `sitemap-blog.xml`
- Alle URLs worden opgeslagen in de database met hun type (`product`, `collection`, `page`, `faq`, `blog`, of `other`).

**Wat als er nieuwe URLs in de sitemap staan?**
- Ze worden automatisch toegevoegd aan de database.
- Ze krijgen status "Niet gecheckt" en worden bij de eerstvolgende inspect-ronde meegenomen.

**Wat als URLs uit de sitemap verdwijnen?**
- Ze worden gemarkeerd als verwijderd (`removed_from_sitemap = TRUE`).
- Ze worden **niet** uit de database gegooid (voor historische rapportage).
- Ze worden niet meer geïnspecteerd of gepusht.

---

## Stap 2: URL-inspectie

**Wat gebeurt er?**
- De tool roept de Google URL Inspection API aan voor elke geselecteerde URL.
- Per URL geeft Google terug:
  - **Verdict** — `PASS` (geïndexeerd), `NEUTRAL` (bekend maar niet geïndexeerd), of `FAIL` (probleem).
  - **Coverage state** — Reden, bijvoorbeeld "Submitted and indexed", "Crawled - currently not indexed", "Discovered - currently not indexed".
  - **Robots.txt-status** — Of Google de pagina mag crawlen.
  - **Last crawl time** — Wanneer Google de pagina voor het laatst bezocht.

**Welke URLs worden eerst gecheckt?**

De tool gebruikt een prioriteitssysteem in `scheduler/strategy.py`:

| Prioriteit | Type URL | Wanneer |
|------------|----------|---------|
| 1 (hoog)   | Nieuwe URLs                | Nog nooit geïnspecteerd |
| 2          | Gefaalde URLs              | Verdict `FAIL` of `NEUTRAL`, langer dan 3 dagen geleden gecheckt |
| 3 (laag)   | Verouderde URLs            | Alle URLs ouder dan 7 dagen sinds laatste check |

**Limieten**
- Google staat per shop maximaal **2.000 inspections per dag** toe.
- De tool draait standaard met `INSPECTION_DAILY_LIMIT_PER_SHOP=15` om binnen GitHub Actions-runtime te blijven; lokaal kun je dit verhogen tot 2.000.
- Elke check kost ~2 seconden (delay om Google niet te overstelpen).

---

## Stap 3: Push (indexering aanvragen)

**Wat gebeurt er?**
- URLs met verdict `NEUTRAL` of `FAIL` worden naar de Google Indexing API gestuurd met type `URL_UPDATED`.
- Dit is een hint aan Google: "Kijk nog eens naar deze pagina."

**Welke URLs worden eerst gepusht?**

| Prioriteit | Type | Reden |
|------------|------|-------|
| 1 (hoog)   | `collection` | Categoriepagina's wegen vaak het zwaarst voor SEO |
| 2          | `product`    | Productpagina's genereren omzet |
| 3          | `page`       | Informatiepagina's |
| 4          | `blog`       | Blogartikelen |
| 5          | `faq`        | Ondersteunende content |
| 6 (laag)   | `other`      | Restcategorie |

URLs die nog nooit zijn gepusht hebben voorrang boven URLs die al eerder zijn gepusht.

**Limieten**
- Google staat **200 pushes per dag** toe over alle eigendommen samen.
- Een URL wordt pas opnieuw gepusht na minimaal **3 dagen** sinds de vorige push.
- De `push_count` in de database houdt bij hoe vaak elke URL is gepusht.

**Werkt het altijd?**
- Nee. De Indexing API is officieel voor vacatures (`JobPosting`) en livestream-events. In de praktijk werkt hij vaak ook voor productpagina's, maar Google geeft geen garantie. Het is een *signaal*, geen commando.

---

## Stap 4: Dagelijkse snapshot

Per shop wordt aan het einde van een run een snapshot opgeslagen met:

- Totaal aantal URLs in de sitemap
- Aantal `PASS` (geïndexeerd)
- Aantal `NEUTRAL` / `FAIL` (niet geïndexeerd)
- Aantal `UNKNOWN` (nog niet gecheckt)

Deze snapshots vullen de trendgrafiek in het dashboard.

---

## GitHub Actions

### Wanneer draait de pipeline?

Standaard alleen handmatig. Voeg een `schedule:` blok toe aan `.github/workflows/daily-indexing.yml` als je een dagelijks schema wil:

```yaml
on:
  schedule:
    - cron: "0 2 * * *"   # 02:00 UTC
  workflow_dispatch: {}
```

### Handmatig starten

1. Ga naar het tabblad **Actions** in je GitHub-repository.
2. Klik links op **"Daily Indexing Pipeline"**.
3. Klik rechts op de knop **"Run workflow"** → **"Run workflow"**.
4. De pipeline start. Klik op de lopende run om de logs te volgen.

### Logs bekijken

1. Open de meest recente workflow-run.
2. Klik op de job **"indexing"**.
3. Klik op de stap **"Run indexing pipeline"** voor de volledige output.

### Tijdsbudget

In de workflow staat `TIME_BUDGET_MINUTES: "30"`. Dit budget geldt alleen voor scan + inspect. Push en snapshot lopen daarna altijd door, zodat het dagelijkse Google-pushbudget volledig benut wordt — ook als de inspect-fase voortijdig stopt.

Lokaal of op een eigen server gelden geen tijdsbudgetten: laat `TIME_BUDGET_MINUTES` weg en de tool draait door tot alles klaar is.

---

## Configuratie aanpassen

### Limieten en intervallen

In `config/settings.py` staan de hoofdparameters. Alle waardes zijn ook via environment variables te overriden:

```python
INSPECTION_DAILY_LIMIT_PER_SHOP = 15   # max checks per shop per run
INDEXING_DAILY_LIMIT            = 200   # max pushes per dag (Google-limiet)
INSPECTION_DELAY_SECONDS        = 2.0   # pauze tussen URL Inspections
INDEXING_DELAY_SECONDS          = 0.5   # pauze tussen pushes
RETRY_INTERVAL_DAYS             = 3     # opnieuw checken na FAIL
RESCAN_INTERVAL_DAYS            = 7     # volledige hercheck-interval
```

### Een shop tijdelijk uitschakelen

In `config/shops.json`, zet `"enabled": false` op de shop:

```json
{
  "shop_id": "mijnshop_pl",
  "name": "Mijn Shop Polska",
  "base_url": "https://www.mijnshop.pl",
  "gsc_site_url": "https://www.mijnshop.pl/",
  "language_code": "pl-PL",
  "enabled": false
}
```

### Een nieuwe shop toevoegen

Voeg een nieuw object toe aan de array in `config/shops.json`:

```json
{
  "shop_id": "mijnshop_xx",
  "name": "Mijn Shop Land",
  "base_url": "https://www.mijnshop.xx",
  "gsc_site_url": "https://www.mijnshop.xx/",
  "language_code": "xx-XX",
  "enabled": true
}
```

Vergeet niet het Service Account ook als **Eigenaar** toe te voegen in Google Search Console voor de nieuwe shop.

---

## Architectuur

```
google-indexing-tool/         ← deze repo (Python + GitHub Actions)
├── config/
│   ├── shops.json            jouw eigen webshops (gitignored)
│   ├── shops.example.json    sjabloon voor nieuwe gebruikers
│   ├── shops.py              JSON-loader + Shop-dataclass
│   └── settings.py           limieten en globale instellingen
├── collectors/
│   └── sitemap.py            URLs ophalen uit sitemaps
├── inspectors/
│   └── url_inspector.py      Google URL Inspection API
├── pushers/
│   └── indexing_pusher.py    Google Indexing API
├── scheduler/
│   └── strategy.py           bepaalt welke URLs aan de beurt zijn
├── db/
│   ├── models.py             database-schema (PostgreSQL)
│   └── queries.py            alle database-queries
├── cli.py                    command-line interface (handmatig draaien)
├── main.py                   pipeline-orchestrator (GitHub Actions / cron)
└── service-account-key.json  Google-sleutel (gitignored)

Database (Neon PostgreSQL)
├── urls                      alle URLs met hun status
├── api_log                   API-gebruik per dag
└── daily_snapshots           dagelijkse trends voor het dashboard

Google Cloud
├── URL Inspection API        statuscheck per URL
├── Web Search Indexing API   indexering aanvragen
└── Service Account           authenticatie (JSON-sleutel)
```

Het bijbehorende dashboard (apart project) leest dezelfde Neon-database en hoeft geen Google APIs aan te roepen.

---

## Veelgestelde vragen

**Worden oude inspecties overschreven?**
Ja. Per URL bewaren we alleen de meest recente inspectiestatus (je wilt altijd het laatste verdict weten). Maar de **dagelijkse snapshots** worden nooit overschreven — elke dag krijgt een eigen rij. Zo blijft de historische trend behouden.

**Waarom verschilt het aantal URLs van wat Google Search Console toont?**
Deze tool telt alleen URLs uit je sitemap. Search Console telt álles wat Google ooit ontdekt heeft, inclusief parameter-varianten, oude pagina's en duplicaten. Onze telling is meestal kleiner én relevanter.

**Wat als Google de Indexing API blokkeert?**
De Indexing API is officieel voor vacatures en livestreams. Voor andere content kan Google verzoeken negeren of weigeren. De tool logt dit als waarschuwing en gaat verder. URL Inspection (status checken) blijft altijd werken.

**Kost het geld?**
Nee, niet als je binnen de gratis tiers blijft:
- GitHub Actions — gratis (2.000 minuten/maand voor private repos)
- Google Cloud APIs — gratis binnen de dagelijkse limieten
- Neon PostgreSQL — gratis tier is ruim voldoende
- Vercel (voor het dashboard) — gratis hobby-tier
