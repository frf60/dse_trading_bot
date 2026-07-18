# DSE Trading & Investment Engine

Two automated systems sharing one Google Sheet and one daily data feed:

1. **Trading engine** — scores a fixed watchlist of stocks across three
   holding horizons (4-13 / 14-29 / 30-60 days), picks up to 2 per horizon
   scoring 9-10/10, sets entry/Stop Loss/Targets from real support and
   resistance levels (falling back to sensible defaults when no clear
   level exists), and tracks each pick through Buy -> Hold -> Sell.
2. **Investment tab** — checks a separate fixed watchlist of "fundamental"
   stocks daily for a long-term (5-20 year) value entry signal (RSI,
   proximity to all-time low, price below its moving average).

Both run automatically once a day via GitHub Actions, reading from a
Google Sheet you feed manually (see "Why data entry is semi-manual" below)
with the previous day's DSE prices.

## Why data entry is semi-manual, not fully automated

dsebd.org's robots.txt disallows automated access to DSE's own price
pages — confirmed by fetching them directly while building this. Rather
than scrape against the site's stated policy, this project treats a human
visiting a public page (you, downloading a CSV from AmarStock) as
categorically different from a bot doing the same thing on a schedule. So:
you paste one day's prices in ~30 seconds; everything downstream —
indicators, scoring, risk, Buy/Hold/Sell, the Investment tab — is fully
automatic.

## One-time setup

1. **Google Sheet + service account**
   - Google Cloud Console -> new project -> enable "Google Sheets API".
   - Create a Service Account -> Keys -> Add key -> JSON -> download it.
   - Share your target Sheet with the service account's email (the
     `client_email` field in the JSON) as **Editor**.
   - `config.SPREADSHEET_ID` is already set to this project's Sheet;
     change it (or `SPREADSHEET_NAME`, used only if `SPREADSHEET_ID` is
     `None`) if you ever point this at a different Sheet.
2. **GitHub repo**
   - Push this folder to a repo.
   - Settings -> Secrets and variables -> Actions -> New repository
     secret -> name it `GOOGLE_SERVICE_ACCOUNT_JSON` -> paste the *entire*
     contents of the downloaded key file.
     **If a key was ever pasted into a chat or anywhere outside this one
     secret field, treat it as compromised — delete it in Google Cloud
     Console and generate a fresh one.**
   - Settings -> Actions -> General -> confirm Actions are enabled.
3. **Test locally before trusting the schedule**
   ```bash
   pip install -r requirements.txt
   python tests/smoke_test.py              # indicators/scoring/risk math, no network
   python tests/test_sheet_data_source.py  # paste-parsing logic, no network
   python tests/test_investment_check.py   # investment-tab logic, no network
   export GOOGLE_SERVICE_ACCOUNT_JSON="$(cat key.json)"
   python run_eod.py                       # real run, real network, real Sheet
   python scripts/investment_check.py      # real run for the Investment tab
   ```
4. Once that works, `.github/workflows/dse_pipeline.yml` takes over
   automatically at **10:30 PM Dhaka time, Sun-Thu** (DSE's trading week).
   Trigger it manually any time from the Actions tab
   (`workflow_dispatch`) — e.g. if you paste later than usual.

## Daily workflow

1. After market close, download that day's price data from AmarStock
   (`amarstock.com/csv-data-download`, or the "Latest Share Price" page's
   CSV export) — a human downloading a file, not automation.
2. Paste it into the **RawStaging** tab of your Google Sheet. Column names
   don't need to match exactly — the parser recognizes common variants
   ("Scrip"/"Trading Code"/"Symbol" all mean ticker, "Close"/"CLOSEP"/"LTP"
   all mean close, etc.) by keyword, not exact position.
3. That's it. At 10:30 PM (or whenever you trigger it), `run_eod.py`
   ingests RawStaging into **RawDailyPrices** (deduplicated, so pasting
   twice is harmless), evaluates existing Hold positions against today's
   close, scans `config.TRADING_WATCHLIST`, and updates Buy/Hold/Sell.
   `scripts/investment_check.py` runs right after, using the same
   freshly-ingested prices, and updates the **Investment** tab.

**Timing:** paste before ~10:20 PM Dhaka time so it's ready when the
scheduled run fires — GitHub's cron is best-effort and can slip a few
minutes. Miss the window? Trigger the workflow manually later —
`run_eod.py` stamps rows with the date at actual execution time, so it's
still correct either way.

## Backfilling history (skip the wait)

New indicators need real history before they mean anything —
`config.MIN_BARS_REQUIRED` is 30-65 bars depending on horizon. To avoid
waiting 2-3 months of daily pastes:

1. Download AmarStock's "CSV Data Download" export for each of the past
   ~60-100 trading days into one folder (each filename must contain its
   date as `YYYY-MM-DD`).
2. ```bash
   python scripts/import_amarstock_csv.py --batch-dir exports/ --out data/amarstock_backfill.csv
   ```
3. Commit `data/amarstock_backfill.csv` to the repo and push. The next
   `run_eod.py` execution (via GitHub Actions, which already has your
   Sheets credentials) finds it automatically and pushes every new
   (date, ticker) row into RawDailyPrices — no separate credentialed
   script run needed on your own machine. Safe to leave the file in the
   repo indefinitely; later runs just find nothing new to add once it's
   all in. Check the "Local backfill file: {...}" line in the run log to
   confirm how many rows were ingested.

## Sheet layout (auto-created on first run)

| Tab | Purpose |
|---|---|
| `RawStaging` | You paste today's price table here. Consumed and cleared by the daily run. |
| `RawDailyPrices` | Canonical OHLCV ledger — append-only, deduplicated on (date, ticker). Everything reads from here. |
| `ActiveTrades` | Every trading-engine pick ever added, one row per (ticker, horizon, date), status ACTIVE / CLOSED_SL / CLOSED_PROFIT, plus `sl_source`/`target_source` showing whether each level came from support/resistance or a fallback. |
| `Buy` | Today's fresh picks (up to `TOP_N_EOD`=2 per horizon). |
| `Hold` | ACTIVE trades currently between Stop Loss and Target 1. |
| `Sell` | Trades that hit Stop Loss or a Target since the last check. |
| `Investment` | Today's Investment-watchlist tickers meeting all 3 long-term conditions — rewritten daily, not a growing log. |

## How the trading engine scores a stock

`config.TRADING_WATCHLIST` (edit freely — add/remove tickers, no other
code changes needed) is scanned **separately for each of the 3 horizons**,
since a 4-13 day swing and a 30-60 day position trade shouldn't be judged
by the same indicator speed:

| | 7+ (4-13 days) | 14+ (14-29 days) | 30+ (30-60 days) |
|---|---|---|---|
| EMA fast/slow | 9/21 | 12/26 | 20/50 |
| RSI period / healthy range | 7 / 50-65 | 14 / 50-70 | 21 / 50-70 |
| MACD | 6/13/5 | 12/26/9 | 19/39/9 |

Each of 8 checks (trend x3, RSI, MACD, "smart money" via OBV-above-its-
-own-MA, volume, price-vs-baseline) contributes to a score out of 10 (see
`config.SCORE_WEIGHTS` for exact points). Only scores of **9 or 10**
qualify (`config.MIN_SCORE`); the top `TOP_N_EOD` (2) per horizon by
score, then RRR, get picked — fewer if fewer clear the bar, which is
normal and expected most days, not an error.

**Entry/Stop Loss/Targets** come from real price structure, not a fixed
formula: Stop Loss looks for the nearest confirmed swing-low support below
entry; Target 1/2 look for the nearest one or two swing-high resistance
levels above entry, within a lookback window that scales with the horizon
(60/90/150 days). When no such level exists — most commonly because a
stock is breaking out to a new high with nothing above it to reference —
targets fall back to a percentage range (7-13% / 14-29% / 35-50%
depending on horizon); Stop Loss falls back to an ATR-based distance when
there's no support below either (e.g. a stock making a new low). Every
pick still has to clear `MIN_RRR` (1.5) using whichever levels were
actually found — a good technical score does not override a bad real
risk/reward.

A stock already an open ACTIVE position for a given horizon is excluded
from that horizon's fresh picks (it can still appear in a *different*
horizon it isn't currently held in).

## How the Investment tab works

`config.INVESTMENT_WATCHLIST` (edit freely) is checked daily for all
three conditions at once:
- RSI(14) <= 45
- Price <= all-time-low-in-your-data x 1.30
- Price < moving average of min(200, days of history you have) — a true
  MA200 once your ledger reaches 200 days, an effective MA-of-everything
  before that.

Matches are written fresh to the Investment tab each run (not
accumulated) — a ticker stops appearing the moment it no longer qualifies.

## Backtesting

`scripts/backtest.py` replays the scoring engine day-by-day over the real
history in RawDailyPrices (walk-forward — never sees data past the
simulated decision day) against `config.TRADING_WATCHLIST`, reporting per
horizon how often a signal actually went on to hit Target 1, Target 2, or
Stop Loss first.

```bash
export GOOGLE_SERVICE_ACCOUNT_JSON="$(cat key.json)"
python scripts/backtest.py                        # default: 3x horizon-days lookforward window
python scripts/backtest.py --lookforward-mult 5    # give 30+ signals more room to resolve
```

With limited total history, longer-horizon signals near the end of your
data will show as "Unresolved" simply because there isn't enough forward
data yet to know — re-run periodically as more days accumulate.

## Customizing

Everything tunable lives in `config.py` with inline comments explaining
the reasoning — no other file should need touching for these:
- **Watchlists**: `TRADING_WATCHLIST`, `INVESTMENT_WATCHLIST` — plain lists.
- **Score weights**: `SCORE_WEIGHTS` (must sum to 10).
- **RSI healthy ranges**: `RSI_RANGES`, per horizon.
- **MACD strictness**: `STRICT_MACD_CROSS`.
- **Fallback target %**: `HORIZONS[...]["fallback_pct_low/high"]`.
- **Swing-point sensitivity**: `SWING_WINDOW` (smaller = more, noisier
  levels found; larger = fewer, more "significant" ones).
- **Quality gates**: `MIN_SCORE`, `MIN_RRR`, `TOP_N_EOD`.

`data_fetcher.py`'s category-CSV path (`get_ticker_universe()`) is no
longer called by anything — a leftover from an earlier broad-universe-scan
design, kept only in case you want to go back to scanning by DSE category
instead of a fixed watchlist.

## Not financial advice

This automates a technical-indicator methodology you specified — it
doesn't predict outcomes, and past technical setups (or backtest results)
don't guarantee future moves. Treat scores, RRR, and backtest win rates as
inputs to your own decision, not a recommendation, and size positions
accordingly.
