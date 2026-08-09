# DSE Algorithmic Watchlist Engine (v3 + Selective Signal)

Three automated systems sharing one Google Sheet and one daily data feed:

1. **Trading engine** — scores `config.TRADING_WATCHLIST` (a fixed, explicit
   list) with ONE composite score out of 25, picks up to `TOP_N_DAILY` new
   buys/day, sets ONE entry + ONE Stop Loss from real support/resistance
   (falling back to sensible defaults when no clear level exists), and
   tracks THREE independent RRR targets (T1/T2/T3) off that one entry.
2. **Investment tab** — checks `config.INVESTMENT_WATCHLIST` (a separate
   fixed list) daily for a long-term (5-20 year) value entry signal (RSI,
   proximity to all-time low, price below its moving average).
3. **Selective Signal engine** — checks `config.SELECTIVE_SIGNAL_WATCHLIST`
   for a short-hold mean-reversion setup (RSI + near 60-day low + DSEX
   relative strength + liquidity filter), takes the top 11/month, and
   tracks each pick with T+2 settlement lock and a hard 15-trading-day
   max hold — fully independent of the trading engine's 3-target model.

All three run automatically once a day via GitHub Actions, reading from a
Google Sheet you feed manually (see "Why data entry is semi-manual" below)
with the previous day's DSE prices.

## Why data entry is semi-manual, not fully automated

dsebd.org's robots.txt disallows automated access to DSE's own price
pages — confirmed by fetching them directly while building this. Rather
than scrape against the site's stated policy, this project treats a human
visiting a public page (you, downloading a CSV from AmarStock) as
categorically different from a bot doing the same thing on a schedule. So:
you paste one day's prices in ~30 seconds; everything downstream —
indicators, scoring, risk, Buy/Hold/Sell, the Investment tab, the
Selective Signal engine — is fully automatic.

## File structure

| File | Purpose |
|---|---|
| `config.py` | Core logic values, score tables, watchlists — the only file you should need to edit for tuning. |
| `indicators.py` | Pure-pandas EMA/RSI/MACD/SMA/swing-point calculations, shared by every engine. |
| `scoring.py` | Trading engine's technical score (RSI 9 + MACD 3 + Volume 3 + MA 3 + DSEX relative-strength 1 + Low-proximity 4 = /23). |
| `risk_manager.py` | Trading engine's setup builder — SL/target placement, SL-quality/Target-quality bonus points (+2, → /25), `rank_and_filter`. |
| `state_manager.py` | Trading engine's ActiveTrades lifecycle (T1/T2/T3 independently tracked, shared stop-loss). |
| `sheet_data_source.py` | Google Sheet ↔ OHLCV bridge: parses RawStaging pastes, maintains RawDailyPrices, serves `get_historical_data()` to every engine. |
| `sheets_manager.py` | Thin gspread wrapper — all Sheets I/O goes through here. |
| `scan.py` | Trading engine's daily scan loop over `TRADING_WATCHLIST`. |
| `selective_signal.py` | Selective Signal engine — screener, monthly top-11 selection, T+2/15-day trade lifecycle. Fully independent of `scan.py`/`risk_manager.py`/`state_manager.py`. |
| `run_eod.py` | Orchestrates the daily run: ingest → trading engine → Selective Signal engine. |
| `scripts/investment_check.py` | Investment tab check — separate GitHub Actions step, not called from `run_eod.py`. |
| `scripts/backtest.py` | Walk-forward backtest of the trading engine against RawDailyPrices. |
| `scripts/import_amarstock_csv.py` | Builds `data/amarstock_backfill.csv` from a folder of AmarStock CSV exports. |

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
   CSV export) — a human downloading a file, not automation. **Make sure
   the export includes an Open column** — the Selective Signal engine
   fills entries at the next trading day's open, so Open is now a
   required field (High/Low/Close/Volume alone are no longer enough).
2. Paste it into the **RawStaging** tab of your Google Sheet. Column names
   don't need to match exactly — the parser recognizes common variants
   ("Scrip"/"Trading Code"/"Symbol" all mean ticker, "Close"/"CLOSEP"/"LTP"
   all mean close, "Open"/"OPENP" all mean open, etc.) by keyword, not
   exact position. A paste missing Open now fails loudly with a clear
   error rather than silently breaking the Selective Signal engine later.
3. That's it. At 10:30 PM (or whenever you trigger it), `run_eod.py`
   ingests RawStaging into **RawDailyPrices** (deduplicated, so pasting
   twice is harmless), evaluates existing Hold positions against today's
   close, scans `config.TRADING_WATCHLIST`, updates Buy/Hold/Sell, then
   runs the Selective Signal engine (scan → enter top-11 signals →
   update T+2/15-day positions) against `config.SELECTIVE_SIGNAL_WATCHLIST`.
   `scripts/investment_check.py` runs right after (as its own Actions
   step), using the same freshly-ingested prices, and updates the
   **Investment** tab.

**Timing:** paste before ~10:20 PM Dhaka time so it's ready when the
scheduled run fires — GitHub's cron is best-effort and can slip a few
minutes. Miss the window? Trigger the workflow manually later —
`run_eod.py` stamps rows with the date at actual execution time, so it's
still correct either way.

## Backfilling history (skip the wait)

New indicators need real history before they mean anything —
`config.MIN_BARS_REQUIRED` is 45 bars for the trading engine,
`config.SS_MIN_BARS_REQUIRED` is 21 for Selective Signal (though its
60-day low lookback keeps improving in quality well past that). To avoid
waiting weeks of daily pastes:

1. Download AmarStock's "CSV Data Download" export for each of the past
   ~60-100 trading days into one folder (each filename must contain its
   date as `YYYY-MM-DD`), **or** use an existing cleaned OHLCV history
   file if you have one (see note below).
2. ```bash
   python scripts/import_amarstock_csv.py --batch-dir exports/ --out data/amarstock_backfill.csv
   ```
   The output must have exactly these columns: `date, ticker, open, high,
   low, close, volume`. If you're hand-assembling this file instead of
   using the script (e.g. from a data-cleaning pipeline that names the
   ticker column `symbol`), rename that column to `ticker` first —
   `ingest_local_backfill()` checks for `ticker` specifically and will
   report a missing-column error rather than silently skipping it.
3. Commit `data/amarstock_backfill.csv` to the repo and push. The next
   `run_eod.py` execution (via GitHub Actions, which already has your
   Sheets credentials) finds it automatically and pushes every new
   (date, ticker) row into RawDailyPrices — no separate credentialed
   script run needed on your own machine. Safe to leave the file in the
   repo indefinitely; later runs just find nothing new to add once it's
   all in. Check the "Local backfill file: {...}" line in the run log to
   confirm how many rows were ingested.

This repo's `data/amarstock_backfill.csv` was built from a 6-month
cleaned history file (Feb 1 – Aug 3, 2026, 465 tickers, including
`00DSEX` and all 44 `TRADING_WATCHLIST`/`SELECTIVE_SIGNAL_WATCHLIST`
tickers) — confirm none of your own watchlist tickers are missing from it
if you edit either watchlist, since a ticker with no backfilled history
just won't score until enough daily pastes accumulate on their own.

## Sheet layout (auto-created on first run)

| Tab | Purpose |
|---|---|
| `RawStaging` | You paste today's price table here (must include Open now). Consumed and cleared by the daily run. |
| `RawDailyPrices` | Canonical OHLCV ledger — append-only, deduplicated on (date, ticker). Everything reads from here. |
| `ActiveTrades` | Every trading-engine pick ever added, one row per (ticker, date), status ACTIVE / CLOSED, plus `sl_source`/`target_source` showing whether each level came from support/resistance or a fallback. |
| `Buy` | Today's fresh trading-engine picks (up to `TOP_N_DAILY`). |
| `Hold` | ACTIVE trading-engine positions currently between Stop Loss and their remaining target(s). |
| `Sell` | Trading-engine trades that hit Stop Loss or their last remaining target since the last check. |
| `Investment` | Today's Investment-watchlist tickers meeting any of the 3 long-term conditions — rewritten daily, not a growing log. |
| `SS_Candidates` | This calendar month's Selective Signal qualifiers accumulated so far (ticker, signal date, relative strength) — rewritten fresh at the start of each new month. |
| `SS_Active` | Open Selective Signal positions — entry, stop, target, gap-risk flag. Rewritten each run as positions close. |
| `SS_Sell` | Closed Selective Signal trades — append-only log with exit price, R-multiple, hold days, P&L, exit reason. |

## How the trading engine scores a stock

`config.TRADING_WATCHLIST` (edit freely — add/remove tickers, no other
code changes needed) is scanned as ONE list — a single composite score
per stock, not split by horizon. "Horizon" survives only as a display
label attached to each of the 3 targets (`config.TARGET_HORIZON_LABEL`),
not as a scoring axis:

- **RSI** (max 9): three separate reads (7d/14d/30d), each tiered — see
  `config.RSI_SCORE_TABLE`.
- **MACD** (max 3): histogram sign + line-vs-signal state, with a bonus
  for a same-day cross-up.
- **Volume** (max 3): today's volume as a multiple of its own 20-day
  average.
- **MA** (max 3): +1 for each of price > MA7/MA14/MA21.
- **DSEX relative strength** (max 1): +1 only if the stock closed up
  while DSEX closed down/flat that day (defaults to 0 if DSEX data isn't
  available yet).
- **Low-proximity** (max 4): the closer today's close is to the lowest
  low in the available history window, the higher the score.
- **SL-quality** (max 1) + **Target-quality** (max 1): computed in
  `risk_manager.py`, not `scoring.py` — +1 if the stop-loss sits on real
  support, +1 if a real resistance level confirms one of the targets.

Total: **/25**, gated by `config.MIN_SCORE` (15). The top `TOP_N_DAILY`
(5) by score (tiebreak: tighter stop first) get picked — fewer if fewer
clear the bar, which is normal and expected most days, not an error.

**Entry/Stop Loss/Targets** come from real price structure, not a fixed
formula: Stop Loss looks for the nearest confirmed swing-low support below
entry, within `SR_LOOKBACK_DAYS` (90 bars); falls back to a flat 6% below
entry_high when none exists. Targets are pure RRR multiples off entry_high
(T1 = 1.0R, T2 = 1.5R, T3 = 2.0R, where R = entry_high − stop_loss) — a
resistance level near a target only earns the target-quality bonus point,
it does not move the target itself.

A stock can be re-picked even while it already has an open ACTIVE
position (this project's current setting — see `run_eod.py`'s comments
if you'd rather exclude already-held tickers again).

## How the Investment tab works

`config.INVESTMENT_WATCHLIST` (edit freely) is checked daily for all
three conditions at once:
- RSI(14) is between 31 and 45 (inclusive)
- Price <= all-time-low-in-your-data x 1.30
- Price < moving average of min(200, days of history you have) — a true
  MA200 once your ledger reaches 200 days, an effective MA-of-everything
  before that.

Matches are written fresh to the Investment tab each run (not
accumulated) — a ticker stops appearing the moment it no longer qualifies.

## How the Selective Signal engine works

`config.SELECTIVE_SIGNAL_WATCHLIST` (defaults to `TRADING_WATCHLIST` —
edit `config.py` to point it at a wider list if you want signal frequency
closer to the original backtest, which scanned the whole DSE) is checked
daily for a short-hold mean-reversion setup, independent of the trading
engine's scoring system entirely:

**Screen** (all three must pass):
- RSI(14) <= 40
- Close within 12% of the trailing 60-day low
- 20-day average daily turnover (volume × close) >= 2,000,000 tk — ensures
  a 100,000 tk buy and later sell can actually be filled without moving
  the price or getting stuck for lack of a counterparty

**Selection:** every ticker that passes is ranked, once per calendar
month, by 20-day relative strength vs DSEX (`stock's 20-day return −
DSEX's 20-day return` — highest first, i.e. stocks resisting the market's
decline). Only the top 11 per month are actually entered; a ticker only
signals once per month (earliest qualifying day wins).

**Entry:** filled at the next trading day's open after the signal.

**Exit:**
- `stop_loss` = fill price × (1 − 6%)
- `target` = fill price × (1 + 9%) — RRR = 1.5
- **T+2 settlement lock:** the purchase day (T) and the next day (T+1)
  are locked — no exit possible even if the stop or target is touched
  intraday. If the low breaches the stop during this window, it's flagged
  `gap_risk = Yes` in SS_Sell but the position stays open regardless —
  this is a real, structural risk of DSE's settlement cycle, not a bug.
- From T+2 onward, stop/target are checked normally each day (stop wins
  if both trigger the same day).
- **Hard 15-trading-day cap:** if neither stop nor target is hit by the
  15th trading day, the position is force-closed at that day's close.
  (An earlier version of this engine let a handful of trades run to 16
  trading days — that was an exit-loop bug, fixed in this version.)

**Backtest reference** (re-run through July 2026, out-of-sample Jun–Jul,
15-day cap strictly enforced): 52 trades, 84.6% win rate overall (86.7%
train / 81.8% test). See `selective_signal.py`'s module docstring and
`config.py`'s `SELECTIVE_SIGNAL_*` block for the exact parameters.

## Backtesting

`scripts/backtest.py` replays the trading engine's scoring day-by-day
over the real history in RawDailyPrices (walk-forward — never sees data
past the simulated decision day) against `config.TRADING_WATCHLIST`,
reporting per horizon-label how often a signal actually went on to hit
Target 1, Target 2, or Stop Loss first.

```bash
export GOOGLE_SERVICE_ACCOUNT_JSON="$(cat key.json)"
python scripts/backtest.py                        # default: 3x horizon-days lookforward window
python scripts/backtest.py --lookforward-mult 5    # give 30+ signals more room to resolve
```

With limited total history, longer-horizon signals near the end of your
data will show as "Unresolved" simply because there isn't enough forward
data yet to know — re-run periodically as more days accumulate.

The Selective Signal engine has its own standalone backtest logic (the
screener in `selective_signal.py`'s `_passes_screen()` plus the same
T+2/15-day lifecycle) rather than reusing `scripts/backtest.py` — its
exit rules don't fit that script's T1/T2/T3 resolution model.

## Customizing

Everything tunable lives in `config.py` with inline comments explaining
the reasoning — no other file should need touching for these:
- **Watchlists**: `TRADING_WATCHLIST`, `INVESTMENT_WATCHLIST`,
  `SELECTIVE_SIGNAL_WATCHLIST` — plain lists.
- **Score weights**: `SCORE_WEIGHTS` (must sum to 10) — trading engine only.
- **RSI healthy ranges**: `RSI_SCORE_TABLE`, per read (7d/14d/30d) — trading engine.
- **Fallback target %** / **quality gates**: `MIN_SCORE`, `MIN_RRR`,
  `TOP_N_DAILY` — trading engine.
- **Swing-point sensitivity**: `SWING_WINDOW` (smaller = more, noisier
  levels found; larger = fewer, more "significant" ones) — trading engine.
- **Selective Signal parameters**: everything prefixed `SS_` — RSI
  threshold, low-proximity %, turnover floor, relative-strength lookback,
  top-N per month, stop/target %, T+2 lock days, max hold days. Toggle the
  whole engine off with `SELECTIVE_SIGNAL_ENABLED = False`.

`data_fetcher.py`'s category-CSV path (`get_ticker_universe()`) is no
longer called by anything — a leftover from an earlier broad-universe-scan
design, kept only in case you want to go back to scanning by DSE category
instead of a fixed watchlist.

## Not financial advice

This automates a technical-indicator methodology you specified — it
doesn't predict outcomes, and past technical setups (or backtest results,
including the Selective Signal engine's 84.6% historical win rate) don't
guarantee future moves. Treat scores, RRR, and backtest win rates as
inputs to your own decision, not a recommendation, and size positions
accordingly.
