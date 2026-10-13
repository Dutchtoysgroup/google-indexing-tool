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
  │ alle shops      │   │ status per URL    │   │ alleen toegestaan  │   │ trends/dashboard │
  └─────────────────┘   └───────────────────┘   └───────────────────┘   └──────────────────┘
        │                       │                       │                       │
   alle URLs              max 2.000/shop/dag       max 200/dag             1 snapshot
   in database            Status per URL            opt-in:               per shop
                          PASS / NEUTRAL / FAIL     vacature/livestream      per dag
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
  - **Canonicals/noindex** — Door Google gekozen en gedeclareerde canonical, indexingState, robots- en fetchstatus; inclusief diagnose en observatietijd in het runrapport.

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

## Stap 3: Optionele notificaties voor toegestane paginatypen

Algemene webshop-URLs worden niet aan `urlNotifications:publish` aangeboden.
De route is standaard uitgeschakeld. Alleen expliciet geconfigureerde URLs met
actueel geverifieerde `JobPosting`- of livestream-structured-data mogen door.
Zie [configuratie en typecontrole](README.md#indexing-api-expliciet-toegestaan-standaard-uit).

Priority-meldingen gaan vóór reguliere meldingen voor toegestane URLs. Het
verzoekbudget wordt gedeeld. Product-/categorie-URLs, ontbrekende toelating en
onbekende paginatypen geven `not_supported`; een verificatiestoring geeft
`validation_failed`. Er volgt in beide gevallen geen publish-aanroep.

HTTP 200 wordt vastgelegd als **`notification_accepted`**. Dit verandert geen
inspectieverdict en telt niet als `indexed`. De velden `last_pushed`/`push_count`
bewaren historisch alleen notificatieacceptatie. Werkelijke indexering wordt
uitsluitend via URL Inspection waargenomen. Notificaties blijven optioneel en
bepalen niet of de noodzakelijke monitoringfasen geslaagd zijn.

---

## Stap 4: Dagelijkse snapshot

Per shop wordt aan het einde van een run een snapshot opgeslagen met:

- Totaal aantal URLs in de sitemap
- Aantal `PASS` (geïndexeerd)
- Aantal `NEUTRAL` / `FAIL` (niet geïndexeerd)
- Aantal `UNKNOWN` (nog niet gecheckt)

Deze snapshots vullen de trendgrafiek in het dashboard. Bekijk ze ook met
`python cli.py report --shop SHOP_ID --history 30`. Notificatieacceptaties tellen
niet als geïndexeerde URLs. Het betreft de laatst bekende inspectiestatus, geen
live controle of bewijs van versnelde indexering.

---

## Runstatus en foutdiagnostiek

`python main.py` en `python cli.py run` gebruiken dezelfde pipeline en exitcode:

- **`success` / exit 0:** scan, geplande inspecties en snapshot zijn voor elke
  ingeschakelde shop geslaagd.
- **`incomplete` / exit 1:** minimaal één noodzakelijke fase is mislukt, gedeeltelijk
  geslaagd of overgeslagen vanwege het tijdsbudget. Andere shops en snapshots
  blijven doorlopen.
- **`failed` / exit 1:** alle noodzakelijke fasen van alle shops zijn mislukt, er
  zijn geen ingeschakelde shops, of database-initialisatie/eindrapportage faalt.

Een API-fout is geen inspectieresultaat: ook wanneer alle HTTP-aanroepen falen
zonder exception uit de batch, krijgt de inspectiefase `failed`. Bij een deels
succesvolle batch wordt dat `incomplete`. Een Google-verdict `FAIL` is daarentegen
wel een geslaagde inspectie: het is de indexeringsstatus van de pagina.

Daglimieten en een lege planning zijn normale situaties en maken de run niet
onvolledig. Push blijft een **optionele** fase met een gedeeld quotum: de aparte
`push`-uitkomst bevat `notification_accepted`-aantallen, URL-uitkomsten en fouten,
maar bepaalt de exitcode niet.

### Duurzaam JSON-rapport

Elke run krijgt een uniek JSON-bestand, bijgewerkt vóór en na elke shopfase:

- Azure WebJob: `/home/data/indexing-pipeline-runs/<run_id>.json`.
- Lokaal: `data/pipeline-runs/<run_id>.json`.
- Override: `PIPELINE_REPORT_DIR=/absoluut/pad` (gebruik blijvende opslag).

Het volledige pad staat in de logs als `Runrapport:`. De Azure-map staat buiten
zowel de tijdelijke WebJob-extractiemap als de gedeployde applicatiebestanden.
Rapporten blijven bewaard totdat ze expliciet worden opgeruimd.

Het rapport bevat UTC-start/eindtijden, de runstatus en per `shop_id` een naam,
shopstatus en `phases.scan`, `phases.inspect` en `phases.snapshot`. Inspecties
bevatten `selected`, `attempted`, `succeeded`, `skipped` en `errors` met de URL en
foutsoort/melding. Een snapshot kan geslaagd zijn terwijl inspecties falen; lees
het runrapport om te bepalen of de snapshot actuele inspecties bevat.

Bestanden worden atomair vervangen en naar disk geflusht. Als het rapport niet
kan worden opgeslagen, stopt het proces met een niet-nul exitcode. Een afgebroken
run houdt `status: incomplete` en `finished_at: null`; `pending`/`running` wijst
op werk dat niet is afgerond. De definitieve shopstatus wordt aan het einde bepaald.

Voorbeeld: diagnostiek van een run bekijken met `jq`:

```bash
jq '{run_id, status, errors, shops, push}' /home/data/indexing-pipeline-runs/<run_id>.json
```

HTTP-fouten in root- of deelsitemaps worden als scanfout opgenomen in het runrapport. Ongeldige
XML of een HTML-foutpagina telt ook als fout. Bij zo'n onvolledige scan worden
de verzamelde URLs niet weggeschreven en bestaande URLs niet als verdwenen
gemarkeerd.

### Offline regressietests

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

De unit-tests gebruiken eigen shopfixtures en gesimuleerde HTTP/API- en databasefouten;
er zijn geen credentials, echte shopconfiguratie of database nodig. Ze controleren
onder andere API-uitval, gedeeltelijk succes, scan- en snapshotfouten,
tijdsbudgetten, quota, rapportopslag en de exitcodes van beide entrypoints.
De Azure-deployworkflow voert deze tests uit vóór deployment. De afzonderlijke
database-integratietests vereisen `TEST_DATABASE_URL`; zonder die variabele
worden alleen die tests overgeslagen.

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

`TIME_BUDGET_MINUTES`, indien ingesteld, geldt alleen voor scan + inspect. De optionele notificatiefase en snapshots lopen daarna door. Het dagquotum is een bovengrens; er worden geen product-URLs verstuurd om het op te vullen.

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
Ja. Per URL bewaren we alleen de meest recente inspectiestatus (je wilt altijd het laatste verdict weten). Een nieuwe run op dezelfde dag werkt de snapshot van die dag bij; eerdere dagen behouden hun eigen rij. Zo blijft de historische trend behouden.

**Waarom verschilt het aantal URLs van wat Google Search Console toont?**
Deze tool telt alleen URLs uit je sitemap. Search Console telt álles wat Google ooit ontdekt heeft, inclusief parameter-varianten, oude pagina's en duplicaten. Onze telling is meestal kleiner én relevanter.

**Wat als Google de Indexing API blokkeert?**
De tool verstuurt uitsluitend toegestane vacature-/livestream-notificaties. Een weigering wordt als notificatiefout geregistreerd; producten blijven via sitemaps en URL Inspection gemonitord. Een notificatie zegt niets over daadwerkelijke indexering.

**Kost het geld?**
Nee, niet als je binnen de gratis tiers blijft:
- GitHub Actions — gratis (2.000 minuten/maand voor private repos)
- Google Cloud APIs — gratis binnen de dagelijkse limieten
- Neon PostgreSQL — gratis tier is ruim voldoende
- Vercel (voor het dashboard) — gratis hobby-tier
