# Hoe werkt de Automatische Indexing Pipeline?

Dit document legt in detail uit hoe de tool werkt, wat er elke nacht gebeurt, en hoe je het kunt monitoren.

---

## Overzicht

```
Elke nacht om 04:00 (NL tijd):

  STAP 1: SCAN          STAP 2: INSPECT         STAP 3: PUSH           STAP 4: SNAPSHOT
  +-----------------+   +-------------------+   +-------------------+   +------------------+
  | Sitemaps        |   | Google URL        |   | Google Indexing   |   | Statistieken     |
  | ophalen van     |-->| Inspection API    |-->| API aanroepen     |-->| opslaan voor     |
  | alle 12 shops   |   | per URL checken   |   | voor failed URLs  |   | dashboard trends |
  +-----------------+   +-------------------+   +-------------------+   +------------------+
        |                      |                       |                       |
   32.000+ URLs          Max 2.000/shop/dag       Max 200/dag            1 snapshot/shop/dag
   in database           Status per URL            Prioriteit:           Indexed vs Not
                         PASS / FAIL               Collections eerst     voor grafieken
```

---

## Stap 1: Sitemap Scan

**Wat gebeurt er?**
- De tool haalt voor elke webshop de sitemap op (bijv. `exittoys.nl/sitemap.xml`)
- Elke sitemap is een "index" die verwijst naar sub-sitemaps:
  - `sitemap-products.xml` (producten)
  - `sitemap-pages.xml` (categoriepagina's, informatiepagina's)
  - `sitemap-faqs.xml` (FAQ pagina's)
  - `sitemap-blog.xml` (blogartikelen)
- Alle URLs worden opgeslagen in de database met hun type (product/page/faq/blog)

**Wat als er nieuwe producten zijn toegevoegd?**
- Nieuwe URLs worden automatisch gevonden en toegevoegd aan de database
- Ze krijgen de status "Niet gecheckt" en worden bij de volgende inspect-ronde meegenomen

**Wat als producten zijn verwijderd?**
- URLs die niet meer in de sitemap staan worden gemarkeerd als "verwijderd"
- Ze worden NIET uit de database verwijderd (voor de historie)
- Ze worden niet meer geInspecteerd of gepusht

---

## Stap 2: URL Inspection

**Wat gebeurt er?**
- De tool roept de Google URL Inspection API aan voor elke URL
- Google geeft per URL terug:
  - **Verdict**: `PASS` (geindexeerd) of `FAIL` / `NEUTRAL` (niet geindexeerd)
  - **Coverage State**: Reden waarom het wel/niet geindexeerd is (bijv. "Submitted and indexed", "Crawled - currently not indexed", "Discovered - currently not indexed")
  - **Robots.txt status**: Of Google de pagina mag crawlen
  - **Laatste crawl datum**: Wanneer Google de pagina voor het laatst heeft bezocht

**Welke URLs worden als eerste gecheckt?**
De tool gebruikt een slim prioriteitssysteem:

| Prioriteit | Type URL | Wanneer |
|------------|----------|---------|
| 1 (hoogst) | Nieuwe URLs | URLs die nog nooit zijn gecheckt |
| 2 | Gefaalde URLs | URLs met verdict FAIL, langer dan 3 dagen geleden gecheckt |
| 3 (laagst) | Verouderde URLs | Alle URLs waarvan de check ouder is dan 7 dagen |

Binnen elke prioriteit worden **collections** (categoriepagina's) eerst gecheckt, daarna producten, dan overige.

**Limieten**
- Google staat maximaal **2.000 inspections per shop per dag** toe
- Met 12 shops = maximaal 24.000 checks per dag
- Bij 2 seconden per check duurt een volledige run ~13 uur
- De eerste keer alle ~32.000 URLs checken duurt dus ~2 dagen

**Wat als de quota op is?**
- De tool slaat automatisch over en gaat door met de volgende shop
- De volgende nacht worden de overgeslagen URLs alsnog gecheckt

---

## Stap 3: Push (Indexering aanvragen)

**Wat gebeurt er?**
- Alle URLs met verdict `FAIL` of `NEUTRAL` (= niet geindexeerd) worden naar Google gestuurd
- De tool gebruikt de Google Indexing API met het verzoek `URL_UPDATED`
- Dit is een signaal aan Google: "Hé, kijk nog eens naar deze pagina"

**Welke URLs worden als eerste gepusht?**

| Prioriteit | Type | Reden |
|------------|------|-------|
| 1 (hoogst) | Collections | Categoriepagina's zijn het belangrijkst voor SEO |
| 2 | Products | Productpagina's genereren verkoop |
| 3 | Pages | Informatiepagina's |
| 4 | Blogs | Blogartikelen |
| 5 (laagst) | FAQ's | Ondersteunende content |

Daarnaast worden URLs die **nog nooit gepusht** zijn voorrang gegeven boven URLs die al eerder gepusht zijn.

**Limieten**
- Google staat maximaal **200 pushes per dag** toe (over alle shops heen)
- Een URL wordt pas opnieuw gepusht als de vorige push meer dan **3 dagen** geleden was
- De `push_count` in de database houdt bij hoe vaak elke URL is gepusht

**Garandeert een push dat Google de pagina indexeert?**
- Nee. De Indexing API is officieel bedoeld voor vacatures en nieuwsartikelen
- In de praktijk werkt het ook voor e-commerce, maar Google geeft geen garantie
- Het is een **signaal**, geen commando. Google beslist uiteindelijk zelf

---

## Stap 4: Dagelijkse Snapshot

**Wat gebeurt er?**
- Per shop wordt een snapshot opgeslagen met:
  - Totaal aantal URLs
  - Aantal geindexeerd (PASS)
  - Aantal niet geindexeerd (FAIL)
  - Aantal nog niet gecheckt (UNKNOWN)
- Deze snapshots vullen de **trend grafiek** in het dashboard

---

## GitHub Actions Workflow

### Wanneer draait het?

| Trigger | Tijdstip | Hoe |
|---------|----------|-----|
| Automatisch | Elke dag om 02:00 UTC (04:00 NL) | Cron schedule |
| Handmatig | Wanneer je wilt | "Run workflow" knop op GitHub |

### Hoe handmatig starten?

1. Ga naar: https://github.com/svendijk2408/google-indexing-tool/actions
2. Klik links op **"Daily Indexing Pipeline"**
3. Klik rechts op de blauwe knop **"Run workflow"**
4. Klik nogmaals op **"Run workflow"**
5. De pipeline start nu. Klik op de running workflow om de logs te volgen.

### Hoe logs bekijken?

1. Ga naar: https://github.com/svendijk2408/google-indexing-tool/actions
2. Klik op de meest recente workflow run
3. Klik op de job **"indexing"**
4. Klik op de stap **"Run indexing pipeline"**
5. Je ziet nu alle log output, inclusief:
   - Hoeveel URLs er per shop zijn gevonden
   - Welke URLs zijn geInspecteerd en hun status
   - Welke URLs zijn gepusht
   - Het eindrapport met totalen

### Wat als de workflow faalt?

| Fout | Oorzaak | Oplossing |
|------|---------|-----------|
| `DATABASE_URL is niet geconfigureerd` | GitHub Secret mist | Voeg `INDEXING_DATABASE_URL` toe aan repo secrets |
| `Geen Google Service Account credentials` | Secret mist of is fout | Check `GOOGLE_SERVICE_ACCOUNT_KEY` secret (base64) |
| `429 Too Many Requests` | Dagelijks quota bereikt | Normaal - wordt morgen opnieuw geprobeerd |
| `403 Forbidden` | Service Account heeft geen rechten | Voeg Service Account toe als Eigenaar in GSC |
| `database "xxx" does not exist` | Verkeerde database naam in URL | Check of de connection string klopt |
| `Timeout` | Te veel URLs in 1 run | Verhoog `timeout-minutes` in workflow file |

---

## Dashboard

Het dashboard (https://google-indexing-dashboard.vercel.app) toont:

### Hoofdpagina
- **Totaal URLs**: Alle URLs uit alle sitemaps
- **Geindexeerd**: URLs waar Google "PASS" op geeft
- **Niet geindexeerd**: URLs waar Google "FAIL" of "NEUTRAL" op geeft
- **Niet gecheckt**: URLs die nog niet via de API zijn gecheckt
- **Coverage**: Percentage geindexeerd van het totaal
- **Trend grafiek**: Hoe de indexering over tijd verandert (na een paar dagen data)
- **Shop kaarten**: Per webshop een kaart met mini-statistieken

### Shop detail (klik op een shop)
- **Coverage pie chart**: Visuele verdeling indexed/not-indexed/unknown
- **Trend grafiek**: Indexering over tijd voor deze specifieke shop
- **URL tabel**: Alle URLs met hun status, filterable op type en verdict
- Je kunt URLs aanklikken om ze in de browser te openen

---

## Tijdlijn: Wat kun je verwachten?

| Dag | Wat er gebeurt |
|-----|---------------|
| Dag 1 | Alle sitemaps gescand (~32.000 URLs). Eerste batch inspections. |
| Dag 2 | ~24.000 URLs geInspecteerd. Eerste pushes van niet-geindexeerde URLs. Dashboard toont eerste echte data. |
| Dag 3 | Alle URLs minstens 1x gecheckt. Trend grafiek begint te vullen. 200 URLs per dag worden gepusht. |
| Week 1 | ~1.400 URLs gepusht. Eerste URLs beginnen geindexeerd te worden na push. |
| Week 2+ | Continue monitoring. Stale checks worden herhaald. Nieuwe producten automatisch opgepikt. |

---

## Configuratie aanpassen

### Meer of minder URLs per dag inspecteren

Bewerk `config/settings.py`:

```python
INSPECTION_DAILY_LIMIT_PER_SHOP = 2000  # Max per shop (Google limiet)
INDEXING_DAILY_LIMIT = 200              # Max pushes totaal (Google limiet)
INSPECTION_DELAY_SECONDS = 2.0          # Pauze tussen API calls
RETRY_INTERVAL_DAYS = 3                 # Opnieuw checken na X dagen bij FAIL
RESCAN_INTERVAL_DAYS = 7                # Volledige hercheck na X dagen
```

### Een shop tijdelijk uitschakelen

Bewerk `config/shops.py` en zet `enabled=False`:

```python
Shop(
    shop_id="exittoys_pl",
    name="EXIT Toys Polska",
    base_url="https://www.exittoys.pl",
    gsc_site_url="https://www.exittoys.pl/",
    language_code="pl-PL",
    enabled=False,  # <-- Tijdelijk uitgeschakeld
),
```

### Een nieuwe webshop toevoegen

Voeg een nieuw `Shop` object toe aan de `SHOPS` lijst in `config/shops.py`:

```python
Shop(
    shop_id="exittoys_xx",        # Unieke ID
    name="EXIT Toys Land",        # Weergavenaam
    base_url="https://www.exittoys.xx",
    gsc_site_url="https://www.exittoys.xx/",  # Zoals in Google Search Console
    language_code="xx-XX",        # Taalcode
),
```

Vergeet niet het Service Account ook als Eigenaar toe te voegen in GSC voor de nieuwe shop.

---

## Handmatig draaien (CLI)

Je kunt de tool ook handmatig draaien vanaf je Mac. Zorg dat je eerst de environment variable zet:

```bash
cd "/Volumes/Ugreen TB5 SSD/EXIT-Code/Scripts/google-indexing-tool"
export DATABASE_URL="postgresql://..."

# Scan alle sitemaps
python3 cli.py scan

# Scan 1 shop
python3 cli.py scan --shop exittoys_nl

# Inspecteer 100 URLs van 1 shop
python3 cli.py inspect --shop exittoys_nl --limit 100

# Push niet-geindexeerde URLs
python3 cli.py push --limit 50

# Bekijk rapport
python3 cli.py report

# Bekijk API usage vandaag
python3 cli.py status

# Draai volledige pipeline
python3 cli.py run
```

---

## Architectuur

```
google-indexing-tool/           <-- Dit project (Python, GitHub Actions)
  config/
    shops.py                    12 webshop definities
    settings.py                 Limieten en configuratie
  collectors/
    sitemap.py                  Haalt URLs op uit sitemaps
  inspectors/
    url_inspector.py            Google URL Inspection API
  pushers/
    indexing_pusher.py           Google Indexing API
  scheduler/
    strategy.py                 Bepaalt welke URLs aan de beurt zijn
  db/
    models.py                   Database schema (PostgreSQL)
    queries.py                  Alle database queries
  cli.py                        Command-line interface
  main.py                       Pipeline orchestrator

google-indexing-dashboard/      <-- Apart project (Next.js, Vercel)
  src/app/
    page.tsx                    Overzicht alle shops
    shop/[shopId]/page.tsx      Detail per shop
  src/components/               UI componenten
  src/lib/db.ts                 Database connectie

Neon PostgreSQL                 <-- Database (cloud)
  urls                          32.000+ URLs met status
  api_log                       API usage tracking
  daily_snapshots               Dagelijkse statistieken

Google Cloud                    <-- APIs
  URL Inspection API            Status checken
  Web Search Indexing API       Indexering aanvragen
  Service Account               Authenticatie
```

---

## Veelgestelde vragen

**Worden oude gegevens overschreven?**
Nee. De inspectie-status per URL wordt geupdate (je wilt altijd de actuele status). Maar de dagelijkse snapshots worden nooit overschreven - elke dag krijgt een eigen rij. URLs worden nooit verwijderd uit de database.

**Waarom verschilt het aantal URLs van Google Search Console?**
Onze tool telt alleen URLs uit de sitemaps (~3.000 per shop). Google Search Console telt alle URLs die Google kent, inclusief parameter-URLs, oude pagina's, en varianten. Onze telling is relevanter: het zijn de pagina's die je daadwerkelijk wilt indexeren.

**Wat als Google de Indexing API blokkeert?**
De Indexing API is officieel voor vacatures/nieuws. Als Google het blokkeert voor e-commerce URLs, logt de tool dit als een waarschuwing. De URL Inspection functionaliteit (status checken) blijft altijd werken.

**Kan ik de cron tijd aanpassen?**
Ja, bewerk `.github/workflows/daily-indexing.yml` en wijzig de cron expressie:
```yaml
schedule:
  - cron: '0 2 * * *'  # 02:00 UTC = 04:00 NL
```

**Kost het geld?**
Nee. Alle gebruikte services zijn gratis:
- GitHub Actions: gratis voor private repos (2.000 minuten/maand)
- Google Cloud APIs: gratis (binnen de dagelijkse limieten)
- Neon PostgreSQL: gratis tier (voldoende voor dit gebruik)
- Vercel: gratis tier (voldoende voor het dashboard)
