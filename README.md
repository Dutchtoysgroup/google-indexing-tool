# Google Indexing Tool

Automatische tool die de indexeringsstatus van je webshops in Google monitort en niet-geïndexeerde URLs naar Google pusht via de officiële Indexing API.

De tool is generiek: of je nu één webshop hebt of er twintig, je vult zelf je domeinen, talen en Google-account in.

---

## Inhoudsopgave

1. [Wat doet deze tool?](#wat-doet-deze-tool)
2. [Wat heb je nodig?](#wat-heb-je-nodig)
3. [Volledige installatie](#volledige-installatie)
4. [Dagelijks gebruik](#dagelijks-gebruik)
5. [CLI-commando's](#cli-commandos)
6. [API-limieten](#api-limieten)
7. [Problemen oplossen](#problemen-oplossen)
8. [Begrippenlijst](#begrippenlijst)

---

## Wat doet deze tool?

De tool draait elke dag (lokaal of via GitHub Actions) en doorloopt vier stappen:

| Stap | Wat | Resultaat |
|------|-----|-----------|
| 1. **Scan** | Haalt alle URLs op uit de sitemaps van je webshops | Volledige lijst van pagina's |
| 2. **Inspect** | Vraagt aan Google: "Is deze URL geïndexeerd?" via de URL Inspection API | Status per URL |
| 3. **Push** | Stuurt niet-geïndexeerde URLs naar Google via de Indexing API | Hint aan Google om opnieuw te kijken |
| 4. **Snapshot** | Slaat dagelijkse statistieken op | Historie voor trendgrafieken |

Alle data wordt opgeslagen in een PostgreSQL-database (we gebruiken Neon, dat een gratis tier heeft). Een apart dashboardproject (Next.js op Vercel) leest dezelfde database uit en toont de status visueel.

---

## Wat heb je nodig?

Voor de installatie heb je deze gratis accounts nodig (en je hoeft geen creditcard op te geven):

1. **Een Google-account** dat eigenaar is van de webshop(s) in [Google Search Console](https://search.google.com/search-console). Deze account wordt gebruikt om de Google Cloud-omgeving aan te maken.
2. **Een GitHub-account** om de tool te draaien (lokaal of via GitHub Actions).
3. **Een Neon-account** ([neon.tech](https://neon.tech)) voor de database.
4. *(Optioneel)* **Een Vercel-account** als je het bijbehorende dashboard wil deployen.

Verder heb je nodig:

- **Python 3.10 of hoger** op je computer (controleer met `python3 --version` in je Terminal). Heb je Python nog niet? Download via [python.org](https://www.python.org/downloads/).
- **Een teksteditor** om configuratiebestanden aan te passen (TextEdit op Mac werkt, maar [VS Code](https://code.visualstudio.com/) is gemakkelijker).

---

## Volledige installatie

Volg deze stappen achter elkaar in één sessie. Alles wat je instelt of kopieert (URLs, e-mailadressen, sleutels) bewaar je in een tekstbestand zodat je niets kwijtraakt.

> 💡 **Tip:** Open dit document op één scherm en je browser op een ander. Zo kun je elke stap meelezen terwijl je doet wat er staat.

---

### Stap 1 — Configureer je webshops

In de map `config/` staan twee bestanden:

- `shops.example.json` → een sjabloon met fictieve voorbeelden
- `shops.json` → jouw eigen configuratie (deze maak je nu aan)

**Wat moet je doen?**

1. Maak een kopie van het sjabloon:
   ```bash
   cd "pad/naar/google-indexing-tool"
   cp config/shops.example.json config/shops.json
   ```
2. Open `config/shops.json` in een teksteditor.
3. Vervang de voorbeeld-shops door jouw eigen webshops. Voor elke shop vul je in:

   | Veld | Wat | Voorbeeld |
   |------|-----|-----------|
   | `shop_id` | Unieke ID, alleen letters/cijfers/underscores | `mijnshop_nl` |
   | `name` | Weergavenaam (mag spaties bevatten) | `Mijn Shop Nederland` |
   | `base_url` | Hoofd-URL van de webshop, zónder slash op het eind | `https://www.mijnshop.nl` |
   | `gsc_site_url` | Exacte URL-property zoals in Google Search Console | `https://www.mijnshop.nl/` |
   | `language_code` | BCP-47 taalcode (`taal-LAND`) | `nl-NL`, `de-DE`, `en-GB` |
   | `enabled` | `true` om mee te scannen, `false` om over te slaan | `true` |

4. Sla het bestand op.

> ⚠️ **Let op:** Het bestand `config/shops.json` staat in `.gitignore` en wordt **niet** mee-gecommit naar Git. Zo blijft jouw configuratie privé en kunnen anderen het bestand niet per ongeluk overschrijven.

---

### Stap 2 — Maak een Google Cloud-project aan

Een Google Cloud-project is de "container" waarin Google APIs voor jouw account beschikbaar zijn. Het is gratis voor het volume dat deze tool gebruikt.

1. Open je browser en ga naar **https://console.cloud.google.com/**
2. Log in met het Google-account dat ook eigenaar is van je shop(s) in Google Search Console.
3. Bovenin de pagina staat een dropdown met projectnamen. Klik erop.
4. Klik in het popup-venster rechtsboven op **"NIEUW PROJECT"**.
5. Vul in:
   - **Projectnaam:** een herkenbare naam, bijv. `Google Indexing Tool`
   - **Organisatie:** laat staan zoals het is
   - **Locatie:** laat staan zoals het is
6. Klik op **"MAKEN"** en wacht ongeveer 10 seconden tot je naar het nieuwe project wordt geleid.

✅ **Controle:** Bovenaan de pagina staat nu de projectnaam die je hebt gekozen.

---

### Stap 3 — Schakel twee Google APIs in

Een API moet "aangezet" worden in je Google Cloud-project, anders weigert Google verzoeken. We hebben er twee nodig:

#### API 1 — Google Search Console API

1. Ga naar **https://console.cloud.google.com/apis/library**
2. Typ in de zoekbalk: `Google Search Console API`
3. Klik op het zoekresultaat **"Google Search Console API"**
4. Klik op de blauwe knop **"INSCHAKELEN"**
5. Wacht tot de pagina laadt (je ziet een bevestiging).

#### API 2 — Web Search Indexing API

1. Ga terug naar **https://console.cloud.google.com/apis/library**
2. Typ in de zoekbalk: `Web Search Indexing API`
3. Klik op het zoekresultaat **"Web Search Indexing API"**
4. Klik op **"INSCHAKELEN"**

✅ **Controle:** Op **https://console.cloud.google.com/apis/enabled** zie je nu beide APIs in de lijst.

---

### Stap 4 — Maak een Service Account aan

Een Service Account is een soort "robot-gebruiker" die namens jou met de Google APIs praat. Het heeft een eigen e-mailadres en een digitale sleutel (een JSON-bestand).

1. Ga naar **https://console.cloud.google.com/iam-admin/serviceaccounts**
2. Controleer dat bovenaan jouw project geselecteerd is.
3. Klik bovenaan op **"+ SERVICEACCOUNT MAKEN"**.
4. Vul in:
   - **Naam:** `indexing-bot` (of een andere herkenbare naam)
   - **ID:** wordt automatisch gevuld
   - **Beschrijving:** bijv. `Automatische indexering voor mijn webshops`
5. Klik op **"MAKEN EN DOORGAAN"**.
6. Bij "Rollen toewijzen": **sla over**, klik op **"DOORGAAN"**.
7. Bij "Gebruikerstoegang verlenen": **sla over**, klik op **"GEREED"**.

Je ziet nu het Service Account in de lijst staan, met een e-mailadres dat eruitziet als:
```
indexing-bot@JOUW-PROJECT.iam.gserviceaccount.com
```

📝 **Kopieer dit e-mailadres** en bewaar het in je tekstbestand. Je hebt het straks nodig om het Service Account toegang te geven tot Search Console.

#### JSON-sleutel downloaden

Nu maak je het "wachtwoord" van de robot in de vorm van een JSON-bestand.

1. Klik op het zojuist aangemaakte Service Account (op de naam, niet op het mailadres).
2. Klik bovenaan op het tabblad **"SLEUTELS"**.
3. Klik op **"SLEUTEL TOEVOEGEN"** > **"Nieuwe sleutel maken"**.
4. Kies **"JSON"** als sleuteltype.
5. Klik op **"MAKEN"**.
6. Er wordt automatisch een `.json`-bestand gedownload, meestal naar je map `Downloads`.

⚠️ **Bewaar dit bestand veilig** — het is letterlijk de sleutel waarmee de tool met Google praat. Iemand met dit bestand kan namens jou indexeringen aanvragen. Plaats het niet in een gedeelde map en commit het nooit in Git.

---

### Stap 5 — Geef het Service Account toegang tot Google Search Console

Nu moeten we de "robot" toegang geven tot elke webshop in Google Search Console. Doe dit voor **iedere webshop** die in `shops.json` staat.

1. Ga naar **https://search.google.com/search-console**
2. Selecteer je eerste webshop bovenaan (de URL-property).
3. Klik linksonder op **"Instellingen"** (het tandwiel-icoon).
4. Klik op **"Gebruikers en rechten"**.
5. Klik op de blauwe knop **"GEBRUIKER TOEVOEGEN"**.
6. Vul in:
   - **E-mailadres:** plak het Service Account-mailadres uit stap 4
   - **Rechten:** kies **"Eigenaar"**
7. Klik op **"Toevoegen"**.

🔁 **Herhaal deze stap voor elke webshop** in `shops.json`.

> 💡 **Tip:** Houd het Service Account-mailadres in je klembord (Cmd+C). Dan kun je het bij elke shop direct plakken (Cmd+V).

---

### Stap 6 — Maak een Neon-database aan

De tool slaat alle URL-statussen en historische gegevens op in PostgreSQL. We gebruiken Neon — dat heeft een gratis tier die ruim voldoende is voor dit gebruik.

1. Ga naar **https://console.neon.tech/** en log in (of maak een account aan).
2. Maak een nieuw project of open een bestaand project.
3. Klik in het linkermenu op **"Databases"**.
4. Klik op **"New Database"**.
5. Geef de database een naam, bijvoorbeeld: `indexing`
6. Klik op **"Create"**.
7. Ga vervolgens in het linkermenu naar **"Dashboard"**.
8. Bij **"Connection string"** klik je op het oogje 👁 om de string zichtbaar te maken.
9. **Belangrijk:** Selecteer in het dropdown-menu naast de connection string je nieuwe database (`indexing`), en niet de standaard `neondb`.
10. Kopieer de hele connection string. Die ziet er ongeveer zo uit:
    ```
    postgresql://neondb_owner:WACHTWOORD@ep-xxxxxx.eu-west-1.aws.neon.tech/indexing?sslmode=require
    ```

📝 **Bewaar deze connection string** in je tekstbestand. Je hebt hem twee keer nodig (één keer voor de tool, één keer voor het dashboard).

---

### Stap 7 — Installeer de tool lokaal en draai een eerste test

Nu hebben we alles om te testen of de tool werkt op jouw computer.

#### Python-pakketten installeren

Open je Terminal (op Mac: Spotlight → "Terminal"). Ga naar de projectmap en installeer de afhankelijkheden:

```bash
# Ga naar de projectmap (pas het pad aan naar jouw situatie)
cd "pad/naar/google-indexing-tool"

# Installeer de Python-pakketten
pip install -r requirements.txt
```

> ℹ️ Als `pip` niet werkt, probeer `pip3 install -r requirements.txt`.

#### Sleutels en database-URL klaarzetten

```bash
# Plaats het JSON-bestand in de projectmap onder de juiste naam
cp ~/Downloads/JOUW-DOWNLOAD-NAAM.json service-account-key.json

# Stel de database-URL in voor deze Terminal-sessie
export DATABASE_URL="postgresql://neondb_owner:WACHTWOORD@ep-xxxxxx.eu-west-1.aws.neon.tech/indexing?sslmode=require"
```

> ℹ️ De export-regel werkt alleen in deze Terminal-sessie. Open je een nieuwe Terminal, dan moet je hem opnieuw uitvoeren.

#### De drie tests uitvoeren

```bash
# Test 1 — Sitemap scannen voor één shop
python3 cli.py scan --shop JOUW_SHOP_ID
# Verwacht: "<naam>: XXX URLs"

# Test 2 — Statusrapport bekijken
python3 cli.py report
# Verwacht: een tabel met aantallen per shop

# Test 3 — Een paar URLs inspecteren (vereist het Service Account)
python3 cli.py inspect --shop JOUW_SHOP_ID --limit 5
# Verwacht: per URL een "[PASS]" of "[NEUTRAL]"-regel
```

✅ Werken alle drie? Dan zit de configuratie goed.

❌ Gaat er iets mis? Zie [Problemen oplossen](#problemen-oplossen) onderaan deze pagina.

---

### Stap 8 — Draaien via GitHub Actions (optioneel)

Wil je dat de tool dagelijks automatisch draait zonder dat je computer aan moet staan? Dan kun je hem op GitHub Actions zetten.

#### 8a. Project naar GitHub pushen

Maak een (privé) repository op GitHub en push de code daarheen. Zorg dat `service-account-key.json` en `config/shops.json` **niet** mee worden gepusht — die staan al in `.gitignore`.

#### 8b. GitHub Secrets instellen

GitHub Secrets zijn versleutelde variabelen die alleen GitHub Actions kan lezen. Niemand anders (ook jijzelf niet meer) kan ze later ophalen.

**Secret 1 — Database-URL:**

1. Ga in je GitHub-repository naar **Settings → Secrets and variables → Actions**.
2. Klik op **"New repository secret"**.
3. Vul in:
   - **Name:** `INDEXING_DATABASE_URL`
   - **Secret:** plak de Neon connection string uit stap 6
4. Klik op **"Add secret"**.

**Secret 2 — Service Account-sleutel (base64):**

GitHub Secrets accepteren geen JSON-bestanden, dus we coderen het bestand eerst als base64-tekst.

1. Open je Terminal.
2. Codeer het JSON-bestand naar je klembord:
   ```bash
   # macOS
   base64 -i ~/Downloads/JOUW-DOWNLOAD-NAAM.json | pbcopy

   # Linux
   base64 -w 0 ~/Downloads/JOUW-DOWNLOAD-NAAM.json | xclip -selection clipboard
   ```
   *(Je ziet niets in de Terminal — dat klopt, de tekst staat nu op je klembord.)*

3. Ga terug naar GitHub: **Settings → Secrets and variables → Actions**.
4. Klik op **"New repository secret"**.
5. Vul in:
   - **Name:** `GOOGLE_SERVICE_ACCOUNT_KEY`
   - **Secret:** plak (Cmd+V) — de gecodeerde tekst wordt geplakt
6. Klik op **"Add secret"**.

✅ **Controle:** Je ziet nu twee secrets in de lijst: `INDEXING_DATABASE_URL` en `GOOGLE_SERVICE_ACCOUNT_KEY`.

#### 8c. Eerste workflow handmatig starten

1. Ga naar het tabblad **"Actions"** in je GitHub-repository.
2. Klik links op **"Daily Indexing Pipeline"**.
3. Klik rechts op **"Run workflow"** → **"Run workflow"**.
4. Wacht 5–15 minuten.
5. Klik op de lopende workflow om de logs in real-time te volgen.

✅ Is alles groen? Dan werkt de pipeline ook op GitHub.

#### 8d. Dagelijks automatisch draaien

Standaard draait de workflow alleen als je hem handmatig start. Wil je een dagelijks schema? Bewerk dan `.github/workflows/daily-indexing.yml` en voeg toe onder `on:`:

```yaml
on:
  schedule:
    - cron: "0 2 * * *"   # 02:00 UTC (= 03:00 in NL-winter, 04:00 in NL-zomer)
  workflow_dispatch: {}
```

---

## Dagelijks gebruik

Na de installatie heb je geen omkijken meer naar de tool. Elke run doorloopt deze stappen:

| Stap | Wat | Limiet |
|------|-----|--------|
| 1. Scan | Alle sitemaps opnieuw ophalen | Geen |
| 2. Inspect | Nieuwe en oude URLs checken bij Google | Configureerbaar (standaard 15 per shop) |
| 3. Push | Niet-geïndexeerde URLs aan Google melden | 200 per dag totaal (Google-limiet) |
| 4. Snapshot | Statistieken opslaan voor de trendgrafiek | 1 per shop per dag |

In de logs zie je per stap wat er gebeurde en wat de eindscore is.

---

## CLI-commando's

Alle commando's draai je vanuit de projectmap, met `DATABASE_URL` ingesteld en `service-account-key.json` aanwezig:

| Commando | Wat het doet |
|----------|--------------|
| `python3 cli.py scan` | Scant sitemaps van álle ingeschakelde shops |
| `python3 cli.py scan --shop SHOP_ID` | Scant alleen de opgegeven shop |
| `python3 cli.py inspect` | Inspecteert URLs (slim geselecteerd op prioriteit) |
| `python3 cli.py inspect --shop SHOP_ID --limit 100` | Max 100 URLs voor één shop |
| `python3 cli.py push` | Pusht niet-geïndexeerde URLs naar Google |
| `python3 cli.py push --limit 50` | Max 50 URLs pushen |
| `python3 cli.py report` | Statusrapport voor alle shops |
| `python3 cli.py report --shop SHOP_ID` | Detailrapport voor één shop |
| `python3 cli.py status` | API-gebruik van vandaag |
| `python3 cli.py run` | Volledige pipeline (scan → inspect → push → snapshot) |

Voeg `--verbose` toe (vóór het commando) voor uitgebreidere logging:
```bash
python3 cli.py --verbose scan
```

---

## API-limieten

| API | Limiet | Toelichting |
|-----|--------|-------------|
| URL Inspection | 2.000 per shop per dag | Officiële Google-limiet |
| Indexing API | 200 per dag (totaal) | Officiële Google-limiet, geldt over alle shops samen |

Je kunt het *standaard* gebruik per run aanpassen via environment variables (handig om GitHub Actions binnen de runtime-budget te houden):

```bash
export INSPECTION_DAILY_LIMIT_PER_SHOP=15   # standaard
export INDEXING_DAILY_LIMIT=200             # standaard
export INSPECTION_DELAY_SECONDS=2.0         # pauze tussen checks
export INDEXING_DELAY_SECONDS=0.5           # pauze tussen pushes
```

---

## Problemen oplossen

| Foutmelding | Oorzaak | Oplossing |
|-------------|---------|-----------|
| `Configuratiebestand niet gevonden: config/shops.json` | Stap 1 overgeslagen | Kopieer `shops.example.json` naar `shops.json` en vul je shops in |
| `DATABASE_URL is niet geconfigureerd` | Environment variable mist | Run `export DATABASE_URL="..."` of zet de GitHub Secret correct |
| `Geen Google Service Account credentials gevonden` | JSON-bestand of secret ontbreekt | Plaats `service-account-key.json` in de projectmap, of zet `GOOGLE_SERVICE_ACCOUNT_KEY` correct (base64) |
| `403 Forbidden` bij inspect | Service Account heeft geen toegang in Search Console | Voeg het Service Account toe als **Eigenaar** in GSC (stap 5) |
| `429 Too Many Requests` | Dagelijks Google-quota op | Normaal — wordt morgen automatisch hervat |
| `Dashboard toont "Nog geen data"` | Nog geen scan gedraaid | Run eerst `python3 cli.py run` of start de GitHub Action |
| `database "xxx" does not exist` | Verkeerde database in connection string | Controleer dat je in Neon de juiste database hebt geselecteerd |

---

## Begrippenlijst

- **Sitemap** — Een XML-bestand met alle URLs van je website. Te vinden op `jouwwebshop.nl/sitemap.xml`.
- **URL Inspection API** — Google-API die per URL vertelt of hij geïndexeerd is.
- **Indexing API** — Google-API waarmee je Google een hint kunt geven om een URL (opnieuw) te crawlen. Officieel bedoeld voor vacatures en nieuws, maar werkt vaak ook voor andere content.
- **Service Account** — Een speciaal Google-account dat namens een applicatie inlogt, zonder mens met wachtwoord.
- **GitHub Secret** — Versleutelde variabele in GitHub. Gebruikt om gevoelige waarden (zoals wachtwoorden en sleutels) veilig te bewaren.
- **Cron** — Een notatie waarmee je tijdschema's beschrijft. `0 2 * * *` betekent "elke dag om 02:00 UTC".
- **PASS / NEUTRAL / FAIL** — Verdict van Google bij een URL Inspection: PASS = geïndexeerd, NEUTRAL = bekend maar niet geïndexeerd, FAIL = probleem.
