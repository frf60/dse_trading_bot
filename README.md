# DSE Algorithmic Watchlist Engine

Scores every DSE A/B category stock (ex. mutual funds) out of 10, builds
7+/14+/30+ day watchlists with ATR-based entry/SL/targets, and tracks each
pick through Buy -> Hold -> Sell using a Google Sheet as the persistent
state store. Runs **once a day via GitHub Actions**, after market close:
ingests whatever you pasted, does a full re-scan, produces tomorrow's Buy
list, and finalizes Hold/Sell against today's close.

## Why data entry is semi-manual, not fully automated

The first real deployment returned 0 stocks after 13+ minutes. Root cause,
confirmed by fetching DSE's own pages directly: **dsebd.org's robots.txt
disallows automated access** to `day_end_archive.php`, `data_archive.php`,
and the latest-share-price pages — exactly what a scraper needs for daily
OHLCV. That's a stated policy, not a bug to route around with retries or a
different user-agent, so this project stopped treating dsebd.org as a live
data source entirely.

What's still fully automatic:
- **Live prices** for Hold/Sell checks — from `m.bullbd.com`'s live table,
  confirmed reachable (not robots.txt-blocked), one request for the whole
  market (`data_fetcher.get_live_price_map()`).
- Everything downstream of having a price: indicators, the /10 score,
  ATR-based SL/targets, RRR filtering, Buy/Hold/Sell state.

What requires ~30 seconds of your time daily: getting each day's
**historical** OHLCV (open/high/low/close/volume) into the system, since
that has to come from somewhere a human is allowed to look, not a bot.

## Daily workflow (using AmarStock — confirmed working)

AmarStock's exports are the recommended source now — confirmed against a
real file: its columns (`TRADING CODE`, `High`, `Low`, `Close`, `Volume`,
and critically `CAT` for category) already match what this project needs,
with no guessing about page structure.

1. Each day after market close, go to
   https://www.amarstock.com/csv-data-download (or the "Latest Share
   Price" page's Export CSV button) and download that day's CSV — a human
   downloading a file, not automation, so none of the robots.txt concerns
   above apply.
2. Either:
   - **Paste it into the `RawStaging` tab** of your Google Sheet — same
     as any other daily paste, `ingest_staging()` handles it automatically
     in the 3 PM run; or
   - **Run it through the import script** locally:
     `python scripts/import_amarstock_csv.py path/to/export.csv YYYY-MM-DD`
     — this also refreshes `data/dse_categories.csv` from the file's `CAT`
     column, so you no longer need to separately visit DSE's category page
     at all.

**Timing** is unchanged from before: have it in RawStaging (or already
ingested via the script) before ~2:50 PM Dhaka time so it's ready for the
3 PM automated run.

## Backfilling history from AmarStock (skip the 2-3 month wait)

AmarStock's CSV Data Download page serves "DSE eod CSV data for any
date" — so instead of waiting ~55 trading days for `MIN_BARS_REQUIRED` to
clear, download the past ~60-100 trading days one file at a time (each
filename must contain its date as `YYYY-MM-DD`), then:

```bash
python scripts/import_amarstock_csv.py --batch-dir exports/ --out data/amarstock_backfill.csv
python scripts/backfill_from_csv.py data/amarstock_backfill.csv
```

The first command combines every dated file in `exports/` into one price
CSV (deduplicated on date+ticker) and refreshes the category CSV from the
most recent file; the second pushes it all into the `RawDailyPrices` sheet
tab in batches. Both were tested against synthetic multi-day data before
shipping — verify a handful of rows against known prices once it's in the
Sheet before trusting it fully.

## What's already been generated from the file you uploaded

`data/dse_categories.csv` and `data/amarstock_prices_2026-07-12.csv` in
this delivery are **real**, not templates — built from your actual
AmarStock export: 425 tickers categorized (277 in A/B, 44 correctly
tagged as funds/bonds/sukuk via the blank-MARKET-CAP signal — see
`scripts/import_amarstock_csv.py`'s docstring for how that was verified),
408 tickers with valid same-day OHLCV. That's one real day in the ledger;
push it to your Sheet (or re-run against more historical exports per
"Backfilling" above) to get moving faster than a cold start.

## What was fixed vs. the original blueprint

Testing the math (not the data source — the formulas) surfaced a real bug:
**the blueprint's SL/T1 ATR multiples make RRR, measured against Target 1,
mathematically incapable of ever reaching 1.5** — 1.5/1.5=1.00 for 7+,
2.5/2.0=1.25 for 14+, 4.0/3.0=1.33 for 30+, regardless of any stock's ATR.
Left as written, the >=1.5 filter would return zero stocks, every day,
forever. `risk_manager.py` gates RRR on **Target 2** instead
(1.67/2.00/2.33 — all clear 1.5), and still shows Target 1 as the closer
partial-profit level. See the comment block at the top of `risk_manager.py`.

## One-time setup

1. **Google Sheet + service account**
   - Google Cloud Console -> new project -> enable "Google Sheets API".
   - Create a Service Account -> Keys -> Add key -> JSON -> download it.
   - Share your target Sheet with the service account's email (the
     `client_email` field in the JSON) as **Editor**.
   - Put the Sheet's ID (from its URL) into `config.SPREADSHEET_ID`.
2. **GitHub repo**
   - Push this folder to a new repo.
   - Settings -> Secrets and variables -> Actions -> New repository
     secret -> name it `GOOGLE_SERVICE_ACCOUNT_JSON` -> paste the *entire*
     contents of the downloaded key file.
   - Settings -> Actions -> General -> confirm Actions are enabled.
3. **Category CSV** — already generated for you from your AmarStock
   upload (see "What's already been generated" below); commit
   `data/dse_categories.csv` as-is. Refresh occasionally by re-running
   `scripts/import_amarstock_csv.py` on a fresh export — categories rarely
   change.
4. **Test locally before trusting the schedule**
   ```bash
   pip install -r requirements.txt
   python tests/smoke_test.py                  # indicators/scoring/risk math, no network
   python tests/test_sheet_data_source.py      # paste-parsing logic, no network
   export GOOGLE_SERVICE_ACCOUNT_JSON="$(cat your-key.json)"
   python run_eod.py                           # real run, real network, real Sheet
   ```
5. Once that works, `.github/workflows/dse_pipeline.yml` takes over at
   3:00 PM Dhaka time, Sun-Thu. Trigger it manually from the
   Actions tab (`workflow_dispatch`) any time — e.g. if you paste later
   than usual on a given day.

## Sheet layout (auto-created on first run)

| Tab | Purpose |
|---|---|
| `RawStaging` | You paste today's DSE price table here. Consumed and cleared by the 3 PM run. |
| `RawDailyPrices` | Canonical OHLCV ledger — append-only, deduplicated on (date, ticker). Everything downstream reads from here. |
| `ActiveTrades` | Every pick ever added, one row per (ticker, horizon, date), status ACTIVE / CLOSED_SL / CLOSED_PROFIT. |
| `Buy` | This run's fresh picks (up to 5 per horizon = up to 15, fewer if a ticker ranks in more than one horizon — expected). |
| `Hold` | ACTIVE trades currently between SL and Target 1. |
| `Sell` | Trades that hit SL or Target 1 since the last check. |

## Design assumptions made without asking (per your instruction not to interrupt)

- MACD's momentum point defaults to the literal "cross above signal" event
  (`STRICT_MACD_CROSS = True`), per the blueprint's wording — a rare
  single-day event. Flip to `False` for "currently above" instead.

## Not financial advice

This automates a technical-indicator methodology you specified — it
doesn't predict outcomes, and past technical setups don't guarantee future
moves. Treat the /10 score and RRR as inputs to your own decision, not a
recommendation, and size positions accordingly.
