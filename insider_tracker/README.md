# Insider-Tracker – Steg 1: Ingest + Databas + Backfill

System som (1) hämtar insynstransaktioner från Finansinspektionens insynsregister,
(2) backtestar historisk avkastning per insynsperson och (3) flaggar nya köp från
högpresterande insiders via Telegram.

**Alla fem moduler är implementerade:** (1) ingest + databas + backfill, (2) kursdata
(Börsdata + EODHD), (3) backtest + scoring + kluster, (4) realtidsflaggning (Telegram),
(5) exit-tracker + månadsrapport. Se respektive avsnitt nedan.

## Verifierat om FI:s dataformat

Bekräftat mot en riktig hämtning (2026-07-15), inte antaget:

- **Stabil export-URL finns** – ingen scraping behövs:
  `GET https://marknadssok.fi.se/Publiceringsklient/sv-SE/Search/Search`
  `?SearchFunctionType=Insyn&button=export&Publiceringsdatum.From=…&Publiceringsdatum.To=…`
- Svar: `text/csv`, teckenkodning **UTF-16**, separator **`;`**, **svensk decimal-komma**.
- 22 kolumner. Insynsperson = `Person i ledande ställning`; transaktionstyp = `Karaktär`
  (`Förvärv`/`Avyttring`); segment finns *inte* för Nasdaq (bara `NASDAQ STOCKHOLM AB`).
- **Exporten kapar vid 1000 rader och `Page`-parametern fungerar inte.** Backfill sker
  därför med datumfönster på `Publiceringsdatum` + **adaptiv split**: ett fönster som når
  taket halveras automatiskt tills det får plats.

### Filter (konfigurerbara i `config.yaml`)
Behåller endast: `Instrumenttyp = Aktie`, `Karaktär ∈ {Förvärv, Avyttring}`,
`Handelsplats ∈ {Spotlight, First North, Nasdaq Stockholm}`, `Status ≠ Makulerad`.

> **Small Cap-filtret:** FI särskiljer inte Nasdaq-segment. Här ingestas hela Nasdaq
> Stockholm; Small Cap-avgränsningen görs via Börsdatas ISIN→segment-mappning i steg 2
> (så vi slipper backfilla om).

## Steg 2: Kursdata-integration

Daglig EOD-kursdata till `prices` samt segment-berikning av `companies`.

Verifierat mot riktiga anrop:
- **Börsdata** (primär): `/markets` (markets = segment: Small Cap=3 …), `/instruments`
  (isin→insId/marketId/sectorId), `/instruments/{insId}/stockprices?from=&to=`
  ({d,o,h,l,c,v}). Full 3-årshistorik. Rate limit ~100/10 s (klienten strular under).
- **EODHD** (fallback): ISIN→symbol via `exchange-symbol-list` (search-API saknas i
  planen), inkl. `delisted=1` mot survivorship bias. **OBS: planen kapar historik till ~1 år.**
- **Segment**: FI särskiljer inte Nasdaq-segment; Börsdatas `marketId` ger Small Cap
  m.m. och skrivs till `companies.segment` – det som gör Small Cap-filtret möjligt.

```bash
python -m insider_tracker.prices.sync_instruments        # berika companies (segment/sektor/insId)
python -m insider_tracker.prices.backfill_prices         # 3 år EOD (Börsdata + EODHD)
python -m insider_tracker.prices.backfill_prices --eodhd-only   # bara fallback
python -m insider_tracker.prices.daily_prices            # dagligt delta (cron)
```
Kräver `BORSDATA_API_KEY`; `EODHD_API_KEY` valfri (fallback). Migration för befintlig
DB: `insider_tracker/db/migration_step2.sql`.

## Steg 3: Backtest + scoring

Beräknar historisk avkastning per köp, scorar insiders och detekterar kluster.

- **Avkastning** (`trade_returns`): +21/+63/+126 handelsdagar efter **publiceringsdatum**
  (agerbart datum), på OMXSPI:s handelsdagskalender. Överavkastning mot OMXSPI,
  minus round-trip-slippage (Spotlight 4 % / First North 2,5 % / Small Cap 1,5 %).
  Survivorship: avnoterat → sista kurs (uppköp); känd konkurs (`bankruptcy_isins`)
  → −100 %. Winsorisering (`max_stock_return`) dämpar penny-stock-extremer.
- **Scoring** (`insider_scores`): viktat snitt av netto-överavkastning (3 mån högst),
  VD/CFO- och beloppsvikt upp, närstående/symboliska ner, shrinkage `n/(n+k)`,
  min 3 köp.
- **Kluster** (`clusters`): ≥3 unika insiders i samma bolag inom rullande 14 dagar,
  backtestad separat med egen avkastningsstatistik.

```bash
python -m insider_tracker.backtest.run              # allt (returns + scores + kluster)
python -m insider_tracker.backtest.run --returns    # bara avkastning
python -m insider_tracker.backtest.run --scores     # bara scoring
python -m insider_tracker.backtest.run --clusters   # bara kluster
```
Migration för befintlig DB: `insider_tracker/db/migration_step3.sql`.

> Observation från datan: att naivt följa *alla* insiderköp underpresterar OMXSPI
> efter slippage (snitt −2 till −3 % överavkastning). Edgen ligger i att *välja*
> högt scorade insiders/kluster – det är precis vad scoring-/klustermodulerna gör.

## Steg 4: Realtidsflaggning (Telegram)

Daglig körning efter ingest + backtest. Tre triggrar, dedupe via `signals`
(idempotent):
1. **Köp** av insider med score i topp-percentilen (default topp 20 %,
   `alerts.score_percentile_threshold`). Symbolköp under `min_amount_sek` triggar inte.
2. **Klusterköp** (≥3 unika insiders / 14 dagar).
3. **Info: försäljning** av insider som tidigare fått köpflagg.

Alert innehåller bolag, marknadsplats/segment, insider + roll, belopp, insiderns
historik (antal köp, snitt 3m), snitt daglig omsättning 30d (likviditetsvarning
< 500k SEK/dag) och länk till FI.

```bash
python -m insider_tracker.alerts.run_alerts --dry-run   # förhandsvisa, skicka inget
python -m insider_tracker.alerts.run_alerts             # skarpt (skickar + sparar signals)
```
Migration: `insider_tracker/db/migration_step4.sql`. Telegram via
`TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`.

### Daglig pipeline (cron, vardagar 18:00 CET)
```
0 18 * * 1-5  cd /path/to/repo && \
  python -m insider_tracker.ingest.daily && \
  python -m insider_tracker.prices.daily_prices && \
  python -m insider_tracker.backtest.run && \
  python -m insider_tracker.alerts.run_alerts >> logs/cron.log 2>&1
```

## Steg 5: Exit-tracker + månadsrapport

Spårar flaggade köp (`signals`) och jämför tre parallella exit-regler i `signal_exits`:
(a) sälj när insidern säljer, (b) fast 3-mån hold (63 handelsdagar), (c) trailing
stop 15 %. Öppna positioner mark-to-marketas mot sista kurs. Månadsrapport via
Telegram jämför hypotetisk netto-avkastning per regel.

```bash
python -m insider_tracker.exits.run --track            # uppdatera signal_exits
python -m insider_tracker.exits.run --report --dry-run # förhandsvisa rapporten
python -m insider_tracker.exits.run --report           # skicka månadsrapport
# Seeda historiska köpflaggor för exit-backtest (ingen Telegram):
python -m insider_tracker.alerts.run_alerts --record-only --lookback 550
```
Migration: `insider_tracker/db/migration_step5.sql`.

### Månadsrapport (cron, t.ex. 1:a varje månad)
```
0 8 1 * *  cd /path/to/repo && python -m insider_tracker.exits.run >> logs/cron.log 2>&1
```

## Paper trading (framåt-validering, out-of-sample)

Backtesten är in-sample. Det enda ärliga testet är att logga live-signaler framåt
och jämföra mot vad backtesten lovade. `paper_trades` loggar en hypotetisk position
per signal med **båda entry-priserna** – teoretiskt (signaldagens stängning) och
realistiskt (nästa handelsdags öppning). Skillnaden = exekveringskostnaden.
`executable`-flaggan separerar likvida från illikvida (< 500k SEK/dag).

```bash
python -m insider_tracker.paper.run --track            # uppdatera paper_trades (dagligt)
python -m insider_tracker.paper.run --weekly           # veckorapport (Telegram)
python -m insider_tracker.paper.run --evaluate         # jämförelsetabell (manuellt, 3/6 mån)
```
Migration: `insider_tracker/db/migration_paper.sql`.

> Spread finns inte i EOD-data, så realistiskt entry = nästa dags öppning (mätbart);
> ren spread kräver quote-data. Seedade signaler är fortfarande in-sample – genuint
> OOS-underlag ackumuleras framåt i tiden. Kör `--evaluate` efter 3 och 6 mån live.

### Cron (utöver den dagliga pipelinen)
```
# lägg till i den dagliga körningen:
&& python -m insider_tracker.paper.run --track
# veckorapport (måndagar 08:00):
0 8 * * 1  cd /path/to/repo && python -m insider_tracker.paper.run --weekly >> logs/cron.log 2>&1
```

## Databas

DB-agnostiskt SQLAlchemy-schema. Lokalt SQLite som standard; byt till Supabase/Postgres
genom att sätta `DATABASE_URL` (ingen kodändring). Tabeller: `companies`, `insiders`,
`insider_roles`, `transactions`, `prices`, `insider_scores`, `signals`.

Ingest är **idempotent** – dedupe på `(person, ISIN, transaktionsdatum, volym, pris)`.

### Persistens-backends

`config.storage.backend` (`auto` | `sqlalchemy` | `supabase_rest`):

- **sqlalchemy** – SQLite lokalt, eller Postgres via `DATABASE_URL` (port 5432).
- **supabase_rest** – Supabase via **PostgREST över HTTPS/443**. Används när miljöns
  nätverkspolicy blockerar Postgres-porten (5432) men släpper igenom HTTPS.
- **auto** (default) – väljer `supabase_rest` om `SUPABASE_URL` +
  `SUPABASE_SERVICE_ROLE_KEY` finns, annars `sqlalchemy`.

#### Sätta upp Supabase (REST-vägen)
1. Skapa tabellerna: kör `insider_tracker/db/schema_supabase.sql` en gång i
   Supabase **SQL Editor** (PostgREST kan inte köra DDL).
2. Sätt miljövariabler (t.ex. i `.env`, gitignorerad):
   ```
   SUPABASE_URL=https://<ref>.supabase.co
   SUPABASE_SERVICE_ROLE_KEY=<service_role JWT från Settings → API>
   ```
   `service_role` kringgår RLS – behandla som ett lösenord.
3. Kör ingest som vanligt (`backend: auto` plockar upp REST automatiskt).

## Användning

```bash
pip install -r requirements-insider.txt

# Torrkörning: hämta + parsa + visa exempel, skriv INGET till DB
python -m insider_tracker.ingest.backfill --dry-run --from 2026-07-01 --to 2026-07-10 --sample 8

# Historisk backfill (default: 3 år tillbaka -> idag)
python -m insider_tracker.ingest.backfill

# Avgränsad backfill
python -m insider_tracker.ingest.backfill --from 2025-01-01 --to 2025-12-31

# Dagligt delta (cron: vardagar 18:00 CET, efter FI:s uppdatering)
python -m insider_tracker.ingest.daily            # senaste 7 dagarna (täcker 3 dagars frist)

# Tester
python -m pytest tests/ -q
```

### Cron-exempel (steg 1)
```
0 18 * * 1-5  cd /path/to/repo && python -m insider_tracker.ingest.daily >> logs/cron.log 2>&1
```

## Miljövariabler
- `BORSDATA_API_KEY` – kursdata (steg 2)
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` – felnotiser (steg 1) och alerts (steg 4)
- `DATABASE_URL` – override för databasen (t.ex. Supabase Postgres)

## Struktur
```
insider_tracker/
  config.py            # laddar config.yaml (+ DATABASE_URL-override)
  logging_setup.py     # loggning till fil + konsol
  db/models.py         # SQLAlchemy-schema (alla tabeller)
  db/session.py        # engine/session, init_db()
  ingest/parser.py     # FI-CSV -> normaliserade, filtrerade poster (+ dedupe-hash)
  ingest/fi_client.py  # HTTP-hämtning med datumfönster + adaptiv split
  ingest/repository.py # idempotenta upserts
  ingest/backfill.py   # CLI: historisk backfill / dry-run
  ingest/daily.py      # CLI: dagligt delta
  notify/telegram.py   # felnotiser / alerts
config.yaml            # alla trösklar, slippage, marknadsplatser, filter
tests/test_parser.py   # parsing-tester (verifierat format)
```
