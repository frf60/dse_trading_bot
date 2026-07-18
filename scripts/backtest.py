"""
Walk-forward backtest: replays the scoring engine day by day over the real
history already in RawDailyPrices, using ONLY data available up to each
simulated "decision day" (no look-ahead — support/resistance detection
inherently can't see beyond that day either, see indicators.find_swing_points),
then checks what actually happened afterward — did that day's signal (if
any, i.e. score >= MIN_SCORE) go on to hit Target 1, Target 2, Stop Loss,
or neither?

Deliberately mirrors run_eod.py's real logic exactly: same
config.TRADING_WATCHLIST, same score_row/build_setup calls with the same
signatures — so results here should be representative of what the live
engine would actually have done, not a different simulation.

Run: python scripts/backtest.py [--lookforward-mult 3]
Needs GOOGLE_SERVICE_ACCOUNT_JSON set (same as scripts/backfill_from_csv.py)
— reads RawDailyPrices directly, no separate data source.

Known limitation with your current data: 30+ needs up to
HORIZON_DAYS["30+"] * lookforward_mult = 90 days of price data AFTER a
signal to fully resolve it. With ~90-100 days of total history right now,
very few (maybe zero) 30+ signals will have enough room to resolve within
this window — most will show as UNRESOLVED, not because the setup is bad,
but because there isn't enough forward data yet. Re-run this periodically
as more daily pastes accumulate; 7+ and 14+ are far less affected.

Assumption worth knowing: simulate_outcome() checks each future day's
High/Low against SL/T1/T2. If a single day's range covers both the stop
and a target, SL is treated as hit first — a conservative assumption,
since daily bars alone can't tell you the actual intraday order.
"""
import sys
from collections import defaultdict
import pandas as pd

from config import MIN_BARS_REQUIRED, HORIZONS, INDICATOR_PARAMS, MIN_SCORE, TRADING_WATCHLIST
from sheets_manager import open_sheet, read_records
from sheet_data_source import RAW_HEADER
from indicators import compute_all
from scoring import score_row
from risk_manager import build_setup

HORIZON_DAYS = {"7+": 13, "14+": 29, "30+": 60}  # upper end of each tier's day range
DEFAULT_LOOKFORWARD_MULT = 3


def load_all_history(sheet) -> dict:
    """{ticker: DataFrame(high,low,close,volume indexed by date)} — whole ledger, one read."""
    records = read_records(sheet, "raw_prices", RAW_HEADER)
    df = pd.DataFrame(records, columns=RAW_HEADER)
    if df.empty:
        return {}
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for col in ("high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["date", "ticker"]).sort_values("date")

    by_ticker = {}
    for ticker, g in df.groupby("ticker"):
        g = g.dropna(subset=["high", "low", "close", "volume"]).set_index("date")
        if len(g) > 0:
            by_ticker[ticker] = g[["high", "low", "close", "volume"]]
    return by_ticker


def simulate_outcome(future: pd.DataFrame, sl: float, t1: float, t2: float) -> dict:
    for i, (_, row) in enumerate(future.iterrows(), start=1):
        if row["low"] <= sl:
            return {"outcome": "SL", "days": i}
        if row["high"] >= t2:
            return {"outcome": "T2", "days": i}
        if row["high"] >= t1:
            return {"outcome": "T1_ONLY", "days": i}
    return {"outcome": "UNRESOLVED", "days": len(future)}


def backtest(lookforward_mult: int = DEFAULT_LOOKFORWARD_MULT):
    sheet = open_sheet()
    print("Loading full price ledger...")
    history = load_all_history(sheet)
    print(f"Loaded history for {len(history)} tickers.")

    tickers = [t for t in TRADING_WATCHLIST if t in history]
    missing = [t for t in TRADING_WATCHLIST if t not in history]
    print(f"{len(tickers)} of {len(TRADING_WATCHLIST)} TRADING_WATCHLIST tickers have price history.")
    if missing:
        print(f"No data yet for: {missing}")

    results = {h: defaultdict(int) for h in HORIZONS}
    resolution_days = {h: [] for h in HORIZONS}

    for ticker in tickers:
        hist = history[ticker]
        n = len(hist)
        for horizon in HORIZONS:
            min_bars = MIN_BARS_REQUIRED[horizon]
            lookforward = HORIZON_DAYS[horizon] * lookforward_mult
            for i in range(min_bars, n - 1):
                window = hist.iloc[: i + 1]  # only data up to and including day i — no look-ahead
                if len(window) < min_bars:
                    continue
                try:
                    enriched = compute_all(window, INDICATOR_PARAMS[horizon])
                    curr, prev = enriched.iloc[-1], enriched.iloc[-2]
                    score = score_row(curr, prev, horizon)["total"]
                except Exception:
                    continue
                if score < MIN_SCORE:
                    continue

                try:
                    setup = build_setup(ticker, window, float(curr["atr14"]), score, horizon)
                except Exception:
                    continue
                if not setup["valid"]:
                    continue

                future = hist.iloc[i + 1: i + 1 + lookforward]
                if future.empty:
                    continue
                outcome = simulate_outcome(future, setup["stop_loss"], setup["target_1"], setup["target_2"])
                results[horizon][outcome["outcome"]] += 1
                resolution_days[horizon].append(outcome["days"])

    print("\n=== Backtest results (walk-forward, no look-ahead) ===")
    for horizon in HORIZONS:
        r = results[horizon]
        total = sum(r.values())
        if total == 0:
            print(f"\n{horizon}: no signals generated in this history window "
                  f"(needs score >= {MIN_SCORE}/10 to fire at all).")
            continue
        wins = r["T1_ONLY"] + r["T2"]
        win_rate = 100 * wins / total
        avg_days = sum(resolution_days[horizon]) / len(resolution_days[horizon])
        print(f"\n{horizon}: {total} signal(s) generated")
        print(f"  Hit Target 2 (full target):     {r['T2']} ({100*r['T2']/total:.1f}%)")
        print(f"  Hit Target 1 only:               {r['T1_ONLY']} ({100*r['T1_ONLY']/total:.1f}%)")
        print(f"  Hit Stop Loss:                    {r['SL']} ({100*r['SL']/total:.1f}%)")
        print(f"  Unresolved (ran out of window):  {r['UNRESOLVED']} ({100*r['UNRESOLVED']/total:.1f}%)")
        print(f"  Win rate (T1 or T2 before SL):   {win_rate:.1f}%")
        print(f"  Average days to resolution:       {avg_days:.1f}")


if __name__ == "__main__":
    mult = DEFAULT_LOOKFORWARD_MULT
    if "--lookforward-mult" in sys.argv:
        mult = int(sys.argv[sys.argv.index("--lookforward-mult") + 1])
    backtest(mult)
