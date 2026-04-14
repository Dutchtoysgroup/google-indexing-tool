# EXIT Toys Google Indexing Tool

Automatische tool die de indexeringsstatus van alle EXIT Toys webshops monitort en niet-geindexeerde URLs pusht naar Google.

## Wat doet deze tool?

1. **Scan** - Verzamelt alle URLs uit de sitemaps van 12 EXIT Toys webshops
2. **Inspect** - Checkt de indexeringsstatus via de Google URL Inspection API
3. **Push** - Pusht niet-geindexeerde URLs naar Google via de Indexing API
4. **Snapshot** - Slaat dagelijkse statistieken op voor het dashboard

De tool draait elke nacht automatisch via GitHub Actions.

## Webshops

NL, BE, DE, AT, UK, IE, SE, DK, ES, IT, PL, FR

---

## Volledige Setup Handleiding

Volg deze stappen precies in volgorde. Doe ze in 1 sessie zodat je niets vergeet.

---

### STAP 1: Google Cloud Project aanmaken

Een Google Cloud Project is de "container" waarin je Google APIs kunt gebruiken. Het is gratis voor ons gebruik.

1. Open je browser en ga naar: **https://console.cloud.google.com/**
2. Log in met het Google-account dat ook toegang heeft tot Google Search Console van EXIT Toys
3. Bovenaan de pagina zie je een dropdown met projectnamen. Klik erop.
4. Klik op **"NIEUW PROJECT"** (rechtsboven in het popup-venster)
5. Vul in:
   - **Projectnaam:** `EXIT Indexing`
   - **Organisatie:** laat staan zoals het is
   - **Locatie:** laat staan zoals het is
6. Klik op **"MAKEN"**
7. Wacht ~10 seconden. Je wordt automatisch naar het nieuwe project geleid.

**Controleer:** Bovenaan de pagina moet nu "EXIT Indexing" staan als actief project.

---

### STAP 2: Google APIs inschakelen

We moeten twee APIs "aanzetten" in ons project. Zonder dit weigert Google onze verzoeken.

#### API 1: Search Console API

1. Ga naar: **https://console.cloud.google.com/apis/library**
2. Typ in de zoekbalk: **Google Search Console API**
3. Klik op het zoekresultaat **"Google Search Console API"**
4. Klik op de grote blauwe knop **"INSCHAKELEN"** (of "ENABLE")
5. Wacht tot de pagina laadt. Je ziet een bevestiging.

#### API 2: Web Search Indexing API

1. Ga terug naar: **https://console.cloud.google.com/apis/library**
2. Typ in de zoekbalk: **Web Search Indexing API**
3. Klik op **"Web Search Indexing API"**
4. Klik op **"INSCHAKELEN"**

**Controleer:** Ga naar https://console.cloud.google.com/apis/enabled - je zou beide APIs moeten zien.

---

### STAP 3: Service Account aanmaken

Een Service Account is als een "robot-gebruiker" die namens jou met Google praat. Het heeft een eigen emailadres en een digitale sleutel (JSON-bestand).

1. Ga naar: **https://console.cloud.google.com/iam-admin/serviceaccounts**
2. Zorg dat bovenaan "EXIT Indexing" als project geselecteerd is
3. Klik op **"+ SERVICEACCOUNT MAKEN"** (bovenaan)
4. Vul in:
   - **Naam:** `indexing-bot`
   - **ID:** wordt automatisch ingevuld (bijv. `indexing-bot@exit-indexing.iam.gserviceaccount.com`)
   - **Beschrijving:** `Automatische indexering van EXIT Toys webshops`
5. Klik op **"MAKEN EN DOORGAAN"**
6. Bij "Rollen" - sla dit over, klik gewoon op **"DOORGAAN"**
7. Bij "Gebruikerstoegang" - sla dit ook over, klik op **"GEREED"**

Je ziet nu je service account in de lijst. **Kopieer het emailadres** (bijv. `indexing-bot@exit-indexing.iam.gserviceaccount.com`). Je hebt dit straks nodig!

#### JSON-sleutel downloaden

1. Klik op het service account dat je zojuist hebt gemaakt (op de naam)
2. Klik bovenaan op het tabblad **"SLEUTELS"** (of "KEYS")
3. Klik op **"SLEUTEL TOEVOEGEN"** > **"Nieuwe sleutel maken"**
4. Kies **"JSON"**
5. Klik op **"MAKEN"**
6. Er wordt automatisch een `.json` bestand gedownload naar je Downloads map
7. **BEWAAR DIT BESTAND GOED** - dit is het "wachtwoord" van de robot

Het bestand heet iets als `exit-indexing-abc123.json`.

---

### STAP 4: Service Account toevoegen aan Google Search Console

Nu moeten we de "robot" (Service Account) toegang geven tot elke EXIT Toys webshop in Google Search Console. Dit moet je voor **alle 12 webshops** doen.

1. Ga naar: **https://search.google.com/search-console**
2. Kies de eerste webshop (bijv. exittoys.nl)
3. Klik links onderaan op **"Instellingen"** (tandwiel-icoon)
4. Klik op **"Gebruikers en rechten"**
5. Klik op de blauwe knop **"GEBRUIKER TOEVOEGEN"**
6. Vul in:
   - **E-mailadres:** het Service Account emailadres (bijv. `indexing-bot@exit-indexing.iam.gserviceaccount.com`)
   - **Rechten:** kies **"Eigenaar"**
7. Klik op **"Toevoegen"**

**HERHAAL dit voor alle 12 webshops:**
- exittoys.nl
- exittoys.be
- exittoys.de
- exittoys.at
- exittoys.co.uk
- exittoys.ie
- exittoys.se
- exittoys.dk
- exittoys.es
- exittoys.it
- exittoys.pl
- exittoys.fr

**Tip:** Houd het emailadres in je klembord (kopieer het), dan kun je het steeds plakken.

---

### STAP 5: Neon Database aanmaken

De tool slaat alle URL-data op in een database. We gebruiken Neon (gratis PostgreSQL in de cloud).

1. Ga naar: **https://console.neon.tech/**
2. Log in met je bestaande account
3. Je hebt al een project. Klik erop om het te openen.
4. Klik in het linkermenu op **"Databases"**
5. Klik op **"New Database"**
6. Naam: **`indexing`**
7. Klik op **"Create"**
8. Ga nu naar **"Dashboard"** (linkermenu)
9. Bij **"Connection string"** - klik op het oogje om de string te tonen
10. **BELANGRIJK:** Zorg dat in de dropdown naast de connection string de database **"indexing"** is geselecteerd (niet "neondb")
11. Kopieer de hele connection string. Die ziet er zo uit:
    ```
    postgresql://neondb_owner:abc123@ep-cool-name-12345.eu-west-1.aws.neon.tech/indexing?sslmode=require
    ```

**Bewaar deze connection string** - je hebt hem twee keer nodig (voor de tool EN het dashboard).

---

### STAP 6: GitHub Secrets instellen voor de Indexing Tool

GitHub Secrets zijn veilige "geheime variabelen" die GitHub Actions kan gebruiken. Niemand anders kan ze zien.

#### Secret 1: Database URL

1. Ga naar: **https://github.com/svendijk2408/google-indexing-tool/settings/secrets/actions**
2. Klik op **"New repository secret"**
3. Vul in:
   - **Name:** `INDEXING_DATABASE_URL`
   - **Secret:** plak de Neon connection string uit stap 5
4. Klik op **"Add secret"**

#### Secret 2: Google Service Account Key

Het JSON-bestand uit stap 3 moet als "gecodeerde tekst" worden opgeslagen. Dat doe je zo:

1. Open je Terminal (Spotlight > typ "Terminal")
2. Typ het volgende commando (vervang het pad naar jouw JSON-bestand):
   ```bash
   base64 -i ~/Downloads/exit-indexing-abc123.json | pbcopy
   ```
   (Dit kopieert de gecodeerde tekst naar je klembord. Je ziet niks in de Terminal, dat is normaal.)
3. Ga terug naar GitHub: **https://github.com/svendijk2408/google-indexing-tool/settings/secrets/actions**
4. Klik op **"New repository secret"**
5. Vul in:
   - **Name:** `GOOGLE_SERVICE_ACCOUNT_KEY`
   - **Secret:** plak (Cmd+V) - de gecodeerde tekst wordt geplakt
6. Klik op **"Add secret"**

**Controleer:** Je hebt nu 2 secrets: `INDEXING_DATABASE_URL` en `GOOGLE_SERVICE_ACCOUNT_KEY`.

---

### STAP 7: Dashboard deployen op Vercel

Het dashboard is een website waar je de indexeringsstatus kunt bekijken.

1. Ga naar: **https://vercel.com/dashboard**
2. Klik op **"Add New..."** > **"Project"**
3. Onder "Import Git Repository" zoek je **"google-indexing-dashboard"**
4. Klik op **"Import"**
5. Bij **"Environment Variables"** voeg je toe:
   - **Key:** `DATABASE_URL`
   - **Value:** plak de Neon connection string uit stap 5
6. Klik op **"Deploy"**
7. Wacht ~1 minuut. Vercel bouwt het dashboard.
8. Je krijgt een URL (bijv. `google-indexing-dashboard-xxx.vercel.app`)

**Dit is je dashboard!** Bookmark deze URL.

Het dashboard toont nu "Nog geen data" - dat is normaal. De data komt na de eerste scan.

---

### STAP 8: Eerste test draaien

Nu gaan we testen of alles werkt. Open je Terminal:

```bash
# Ga naar het project
cd "/Volumes/Ugreen TB5 SSD/EXIT-Code/Scripts/google-indexing-tool"

# Installeer de benodigde Python packages
pip install -r requirements.txt

# Stel de database URL in (plak jouw Neon connection string)
export DATABASE_URL="postgresql://neondb_owner:JOUW_WACHTWOORD@ep-JOUW-SERVER.eu-west-1.aws.neon.tech/indexing?sslmode=require"

# Test 1: Scan de sitemaps van 1 shop
python cli.py scan --shop exittoys_nl
# Je zou moeten zien: "EXIT Toys Nederland: XXX URLs"

# Test 2: Bekijk het rapport
python cli.py report
# Je ziet nu een tabel met aantallen per shop

# Test 3: Inspecteer een paar URLs (vereist Service Account)
# Kopieer het JSON-bestand naar het project:
cp ~/Downloads/exit-indexing-*.json service-account-key.json

python cli.py inspect --shop exittoys_nl --limit 5
# Je zou per URL een [PASS] of [FAIL] moeten zien
```

Als de scan werkt, werkt de database connectie. Als de inspect werkt, werkt het Service Account.

---

### STAP 9: GitHub Actions testen

De tool draait automatisch elke nacht om 02:00 UTC (04:00 Nederlandse tijd). Maar je kunt hem ook handmatig starten:

1. Ga naar: **https://github.com/svendijk2408/google-indexing-tool/actions**
2. Klik links op **"Daily Indexing Pipeline"**
3. Klik rechts op **"Run workflow"** > **"Run workflow"**
4. Wacht ~5-15 minuten
5. Klik op de running workflow om de logs te bekijken
6. Bij "Run indexing pipeline" zie je de output van de tool

Als alles groen is, werkt de automatische pipeline!

---

### STAP 10: Dashboard bekijken

Na de eerste succesvolle scan (stap 8 of 9) verschijnen er gegevens in het dashboard:

1. Ga naar je Vercel dashboard URL
2. Je ziet nu:
   - Bovenaan: totale statistieken
   - Kaartjes per webshop met coverage percentage
   - Klik op een webshop voor details + URL-tabel

De trend grafieken vullen zich na een paar dagen automatisch.

---

## Hoe werkt het daarna?

Je hoeft **niks meer te doen**. De tool draait elke nacht automatisch:

- **02:00 UTC:** GitHub Actions start de pipeline
- **Scan:** Alle sitemaps worden opnieuw opgehaald
- **Inspect:** Nieuwe en probleem-URLs worden gecheckt (max 2000/shop/dag)
- **Push:** Niet-geindexeerde URLs worden naar Google gestuurd (max 200/dag)
- **Snapshot:** Statistieken worden opgeslagen voor de trend grafieken

Het dashboard toont altijd de actuele status.

---

## CLI Commando's (voor handmatig gebruik)

| Commando | Beschrijving |
|----------|-------------|
| `python cli.py scan` | Verzamel URLs uit sitemaps |
| `python cli.py scan --shop exittoys_nl` | Scan alleen NL shop |
| `python cli.py inspect` | Inspecteer URLs (slim geselecteerd) |
| `python cli.py inspect --limit 100` | Max 100 URLs per shop |
| `python cli.py push` | Push niet-geindexeerde URLs |
| `python cli.py push --limit 50` | Max 50 URLs pushen |
| `python cli.py report` | Statusrapport alle shops |
| `python cli.py report --shop exittoys_nl` | Rapport voor NL |
| `python cli.py status` | API usage vandaag |
| `python cli.py run` | Volledige pipeline |

## API Limieten

| API | Limiet | Toelichting |
|-----|--------|-------------|
| URL Inspection | 2.000/dag/shop | Checkt of een URL geindexeerd is |
| Indexing API | 200/dag totaal | Vraagt Google om een URL te indexeren |

## Problemen oplossen

| Probleem | Oplossing |
|----------|-----------|
| "DATABASE_URL is niet geconfigureerd" | Zet de environment variable of check de GitHub Secret |
| "Geen Google Service Account credentials" | Check of het JSON-bestand op de juiste plek staat, of de GitHub Secret correct is |
| "403 Forbidden" bij inspection | Service Account heeft geen (Eigenaar-)rechten in GSC |
| Dashboard toont "Nog geen data" | Voer eerst een scan uit |
| GitHub Actions faalt | Check de logs in het Actions tabblad op GitHub |
