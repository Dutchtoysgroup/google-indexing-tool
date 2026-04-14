# EXIT Toys Google Indexing Tool

Automatische tool die de indexeringsstatus van alle EXIT Toys webshops monitort en niet-geindexeerde URLs pusht naar Google.

## Wat doet deze tool?

1. **Scan** - Verzamelt alle URLs uit de sitemaps van 12 EXIT Toys webshops
2. **Inspect** - Checkt de indexeringsstatus via de Google URL Inspection API
3. **Push** - Pusht niet-geindexeerde URLs naar Google via de Indexing API
4. **Snapshot** - Slaat dagelijkse statistieken op voor het dashboard

## Webshops

NL, BE, DE, AT, UK, IE, SE, DK, ES, IT, PL, FR

## Setup

### 1. Google Cloud Project

1. Ga naar [Google Cloud Console](https://console.cloud.google.com/)
2. Maak een nieuw project: **"EXIT Indexing"**
3. Zoek en schakel in:
   - **Google Search Console API**
   - **Web Search Indexing API**

### 2. Service Account

1. Ga naar **IAM en beheer > Serviceaccounts**
2. Klik **Serviceaccount maken**, geef het een naam (bijv. "indexing-bot")
3. Kopieer het emailadres (eindigt op `.iam.gserviceaccount.com`)
4. Klik op het account > **Sleutels > Sleutel toevoegen > JSON**
5. Download het JSON-bestand

### 3. Google Search Console Rechten

Voor **elke** EXIT Toys webshop in [Google Search Console](https://search.google.com/search-console):

1. Ga naar **Instellingen > Gebruikers en rechten**
2. Klik **Gebruiker toevoegen**
3. Vul het Service Account emailadres in
4. Geef rechten: **Eigenaar** (nodig voor Indexing API)

### 4. Neon Database

1. Ga naar je [Neon account](https://console.neon.tech/)
2. Maak een nieuwe database `indexing` aan in je bestaande project
3. Kopieer de connection string

### 5. GitHub Repository

1. Maak een nieuwe GitHub repo (bijv. `exit-indexing-tool`)
2. Push deze code
3. Ga naar **Settings > Secrets and variables > Actions**
4. Voeg toe:
   - `INDEXING_DATABASE_URL` - Neon connection string
   - `GOOGLE_SERVICE_ACCOUNT_KEY` - Base64-encoded JSON key:
     ```bash
     base64 -i service-account-key.json | pbcopy
     ```

### 6. Lokaal testen

```bash
# Installeer dependencies
pip install -r requirements.txt

# Zet environment variables
export DATABASE_URL="postgresql://..."
# Of plaats service-account-key.json in de project root

# Initialiseer database
python cli.py scan --shop exittoys_nl

# Test inspection (vereist Service Account)
python cli.py inspect --shop exittoys_nl --limit 5

# Bekijk rapport
python cli.py report
```

## CLI Commando's

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

| API | Limiet |
|-----|--------|
| URL Inspection | 2.000 per dag per shop |
| Indexing API | 200 per dag totaal |

## GitHub Actions

De pipeline draait automatisch dagelijks om 02:00 UTC via GitHub Actions.
Handmatig triggeren: **Actions > Daily Indexing Pipeline > Run workflow**
