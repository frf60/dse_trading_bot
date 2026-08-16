"""
One-time backfill: bulk-loads historical OHLCV into RawDailyPrices from a
local CSV, so you don't have to paste daily for ~2-3 months before EMA50/
ATR14 have enough bars to be meaningful (MIN_BARS_REQUIRED in config.py).

Run once, from the repo root: python scripts/backfill_from_csv.py path/to/history.csv

Expected CSV columns (case-insensitive, order doesn't matter):
    date, ticker, open, high, low, close, volume
("open" IS required -- Branch B of the combined regime model screens on
a green candle (close > open), so a row missing open can't be scored for
Branch B eligibility. sheet_data_source.RAW_HEADER now includes it too;
writing rows without it would silently shift every column one slot over
in the sheet -- this file used to skip open, which was a real bug, fixed
here.)

Where to get such a CSV: candidate public datasets exist (e.g. searches
turn up a Mendeley Data DSE end-of-day dataset and Kaggle DSE historical
datasets) but their exact schema and accuracy were NOT verified while
building this — sanity-check a handful of rows against known prices for a
few tickers/dates before trusting the backfill. Garbage in the ledger
produces garbage scores/ATR out, silently.

Safe to re-run: de-duplicates on (date, ticker) against whatever's already
in RawDailyPrices, same as the daily paste-import path.

IMPORTANT -- run_weekly.py's regime switch (weekly_engine._is_uptrend_series)
needs weekly_config.INDEX_SYMBOL ("00DSEX") present in RawDailyPrices with
real historical bars, same as any other ticker. If your backfill CSV
doesn't include a "00DSEX" row for every date, add it (as its own
ticker="00DSEX" rows) before running this -- otherwise every weekly scan
silently treats every week as NOT-UPTREND (Branch A only) with the
regime check just seeing no data at all, matching combined_regime_model.py's
"index missing" fallback rather than failing loudly.
"""
import sys
import os

# Needed because this script lives in scripts/, not the repo root -- when
# run as `python scripts/backfill_from_csv.py ...`, Python only puts
# scripts/ on sys.path, not the repo root where sheets_manager.py and
# sheet_data_source.py actually live. Same fix as scripts/inspect_ticker.py.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import pandas as pd
from sheets_manager import open_sheet, read_records, append_rows_with_retry
from sheet_data_source import RAW_HEADER


def _match(colnames, *keywords):
    lowered = [str(c).strip().lower() for c in colnames]
    for i, c in enumerate(lowered):
        if any(k in c for k in keywords):
            return colnames[i]
    return None


def main(csv_path: str):
    df = pd.read_csv(csv_path)
    col_ticker = _match(df.columns, "ticker", "trading code", "scrip", "symbol", "code")
    col_date = _match(df.columns, "date")
    col_open = _match(df.columns, "openp", "open")
    col_high = _match(df.columns, "high")
    col_low = _match(df.columns, "low")
    col_close = _match(df.columns, "close", "ltp")
    col_volume = _match(df.columns, "volume", "vol")

    missing = [n for n, c in [("ticker", col_ticker), ("date", col_date), ("open", col_open),
                               ("high", col_high), ("low", col_low),
                               ("close", col_close), ("volume", col_volume)] if c is None]
    if missing:
        raise SystemExit(f"Couldn't find columns for {missing} in {csv_path}. "
                          f"Found columns: {list(df.columns)}")

    df = df.rename(columns={
        col_ticker: "ticker", col_date: "date", col_open: "open", col_high: "high",
        col_low: "low", col_close: "close", col_volume: "volume",
    })
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df = df.dropna(subset=["ticker", "close"])

    print(f"Loaded {len(df)} rows covering {df['ticker'].nunique()} tickers "
          f"from {df['date'].min()} to {df['date'].max()}.")

    if "00DSEX" not in set(df["ticker"].astype(str)):
        print("  WARNING: no '00DSEX' rows found in this CSV. The weekly regime "
              "switch (weekly_engine._is_uptrend_series) needs 00DSEX history in "
              "RawDailyPrices -- without it every week will silently fall back to "
              "NOT-UPTREND (Branch A only). Add 00DSEX rows separately if this CSV "
              "doesn't already have them elsewhere.")

    sheet = open_sheet()
    existing = read_records(sheet, "raw_prices", RAW_HEADER)
    existing_keys = {(str(r["date"]), str(r["ticker"])) for r in existing}

    new_rows = []
    for _, row in df.iterrows():
        key = (row["date"], str(row["ticker"]))
        if key in existing_keys:
            continue
        new_rows.append([row["date"], row["ticker"], row["open"], row["high"], row["low"],
                          row["close"], row["volume"]])

    print(f"{len(new_rows)} new rows to append ({len(df) - len(new_rows)} already present).")
    if new_rows:
        # gspread has per-request size limits — batch in chunks rather than
        # one giant append_rows call for large backfills. append_rows_with_retry
        # backs off automatically if a burst of chunks trips the write quota.
        CHUNK = 2000
        for i in range(0, len(new_rows), CHUNK):
            chunk = new_rows[i:i + CHUNK]
            append_rows_with_retry(sheet, "raw_prices", RAW_HEADER, chunk)
            print(f"  appended rows {i} to {i + len(chunk)}")
            time.sleep(1)

    print("Backfill complete.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/backfill_from_csv.py path/to/history.csv")
    main(sys.argv[1])
