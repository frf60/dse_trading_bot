"""
Turns AmarStock exports into what this project needs. AmarStock has two
different export formats and this handles both:

  "Latest Share Price" page — TRADING CODE, LTP, CAT, MARKET CAP, High,
  Low, Close, Volume, etc. Has category (CAT) and fund/bond detection
  (blank MARKET CAP) built in.

  "CSV Data Download" page (amarstock.com/csv-data-download, "DSE eod CSV
  data for any date") — simpler: Date, Scrip, Open, High, Low, Close,
  Volume. No CAT or MARKET CAP columns at all — this format is what most
  people end up using for backfilling and daily pastes, since it's the
  one built for pulling a specific date.

Column matching is keyword-based (case-insensitive substring), not exact
names, specifically so both formats — and whatever AmarStock calls things
next year — work without code changes. "Scrip" is DSE/AmarStock's word for
ticker symbol; recognized alongside "trading code"/"symbol"/"code".

Two modes:

  Single file (today's export, or one historical date):
    python scripts/import_amarstock_csv.py path/to/export.csv 2026-07-12

  Batch (a folder of historical exports, for backfilling — pull ~60-100
  past trading days this way instead of waiting 2-3 months of daily
  pastes to clear MIN_BARS_REQUIRED):
    python scripts/import_amarstock_csv.py --batch-dir exports/ --out data/amarstock_backfill.csv
  Each file in the folder must have its date somewhere in the filename
  (YYYY-MM-DD, e.g. "2026-05-01.csv" or "AmarStock-2026-05-01.csv").

Either mode writes:
1. data/dse_categories.csv (ticker, category, sector) — ONLY if the file
   has CAT and MARKET CAP columns (the "Latest Share Price" format). If
   not (e.g. every "CSV Data Download" file), this step is skipped with a
   message rather than crashing — build categories once from a "Latest
   Share Price" export instead, then use CSV Data Download exports purely
   for price backfilling.
2. A backfill-ready price CSV (date, ticker, high, low, close, volume) —
   feed straight into scripts/backfill_from_csv.py. Rows with no traded
   price (suspended/non-trading tickers, bonds) are dropped.

Matched columns already line up with sheet_data_source.py's paste parser,
so any of these files can also be pasted directly into the RawStaging tab
as a daily update instead of copying an HTML table by hand.
"""
import re
import sys
import glob
import os
import pandas as pd

CATEGORY_OUT = "data/dse_categories.csv"
FUND_SECTOR_LABEL = "Mutual Funds"  # matches config.EXCLUDED_SECTORS exactly
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _match(columns, *keywords):
    """Case-insensitive substring match; returns the original column name or None."""
    lowered = {str(c).strip().lower(): c for c in columns}
    for low, orig in lowered.items():
        if any(k in low for k in keywords):
            return orig
    return None


def build_category_csv(df: pd.DataFrame, out_path: str = CATEGORY_OUT):
    """Returns a categories DataFrame, or None if this file doesn't have CAT/MARKET CAP."""
    col_cat = _match(df.columns, "cat")
    col_mktcap = _match(df.columns, "market cap", "marketcap")
    col_ticker = _match(df.columns, "trading code", "scrip", "symbol", "code")
    if col_cat is None or col_mktcap is None or col_ticker is None:
        return None

    is_fund_or_bond = df[col_mktcap].isna()
    cats = pd.DataFrame({
        "ticker": df[col_ticker].astype(str).str.strip(),
        "category": df[col_cat].astype(str).str.strip(),
        "sector": is_fund_or_bond.map({True: FUND_SECTOR_LABEL, False: ""}),
    })
    # Structurally-corrupted rows (e.g. a bond whose columns shifted in the
    # export, CAT showing "-") — drop rather than guess.
    cats = cats[cats["category"].isin(["A", "B", "N", "Z", "Y"])]
    cats.to_csv(out_path, index=False)
    return cats


def build_price_rows(df: pd.DataFrame, run_date: str) -> pd.DataFrame:
    col_ticker = _match(df.columns, "trading code", "scrip", "symbol", "code")
    col_high = _match(df.columns, "high")
    col_low = _match(df.columns, "low")
    col_close = _match(df.columns, "closep", "close", "ltp")
    col_volume = _match(df.columns, "volume", "vol")

    missing = [n for n, c in [("ticker", col_ticker), ("high", col_high), ("low", col_low),
                               ("close", col_close), ("volume", col_volume)] if c is None]
    if missing:
        raise RuntimeError(f"Couldn't find columns for {missing}. Found: {list(df.columns)}")

    numeric = df.copy()
    for col in (col_high, col_low, col_close, col_volume):
        numeric[col] = pd.to_numeric(numeric[col], errors="coerce")
    numeric = numeric.dropna(subset=[col_high, col_low, col_close, col_volume])
    return pd.DataFrame({
        "date": run_date,
        "ticker": numeric[col_ticker].astype(str).str.strip(),
        "high": numeric[col_high],
        "low": numeric[col_low],
        "close": numeric[col_close],
        "volume": numeric[col_volume],
    })


def run_single(csv_path: str, run_date: str, price_out_path: str):
    df = pd.read_csv(csv_path)
    cats = build_category_csv(df)
    prices = build_price_rows(df, run_date)
    prices.to_csv(price_out_path, index=False)

    if cats is not None:
        ab_count = cats[cats["category"].isin(["A", "B"])].shape[0]
        fund_count = (cats["sector"] == FUND_SECTOR_LABEL).sum()
        print(f"Categories: {len(cats)} tickers written to {CATEGORY_OUT} "
              f"({ab_count} in category A/B, {fund_count} tagged as funds/bonds).")
    else:
        print("Categories: skipped — this file has no CAT/MARKET CAP columns "
              "(that's normal for CSV Data Download exports). Use a 'Latest Share "
              "Price' export once to build data/dse_categories.csv instead.")
    print(f"Prices: {len(prices)} tickers with valid {run_date} OHLCV written to {price_out_path} "
          f"({len(df) - len(prices)} skipped — no trade / suspended / bond).")


def run_batch(batch_dir: str, out_path: str):
    files = sorted(glob.glob(os.path.join(batch_dir, "*.csv")))
    if not files:
        raise SystemExit(f"No .csv files found in {batch_dir}")

    all_prices = []
    latest_df, latest_date = None, None
    skipped_files = []

    for path in files:
        m = DATE_RE.search(os.path.basename(path))
        if not m:
            skipped_files.append((path, "no YYYY-MM-DD found in filename"))
            continue
        run_date = m.group(1)
        try:
            df = pd.read_csv(path)
            all_prices.append(build_price_rows(df, run_date))
        except Exception as e:
            skipped_files.append((path, str(e)))
            continue
        if latest_date is None or run_date > latest_date:
            latest_date, latest_df = run_date, df

    if not all_prices:
        raise SystemExit("No usable files found — check filenames contain YYYY-MM-DD, "
                          f"and see per-file errors: {skipped_files}")

    combined = pd.concat(all_prices, ignore_index=True)
    combined = combined.drop_duplicates(subset=["date", "ticker"])
    combined.to_csv(out_path, index=False)

    cats = build_category_csv(latest_df) if latest_df is not None else None

    print(f"Processed {len(files) - len(skipped_files)}/{len(files)} files "
          f"covering {combined['date'].nunique()} trading days, "
          f"{combined['ticker'].nunique()} distinct tickers.")
    print(f"Combined price rows written to {out_path} — feed this into "
          f"scripts/backfill_from_csv.py next (or commit it as "
          f"data/amarstock_backfill.csv for run_eod.py to pick up automatically).")
    if cats is not None:
        ab_count = cats[cats["category"].isin(["A", "B"])].shape[0]
        print(f"Categories refreshed from {latest_date}'s file: {len(cats)} tickers "
              f"({ab_count} in category A/B).")
    else:
        print("Categories: skipped — these files have no CAT/MARKET CAP columns "
              "(normal for CSV Data Download exports). Build data/dse_categories.csv "
              "once from a 'Latest Share Price' export instead.")
    if skipped_files:
        print(f"Skipped {len(skipped_files)} file(s):")
        for path, reason in skipped_files:
            print(f"  {path}: {reason}")


if __name__ == "__main__":
    if "--batch-dir" in sys.argv:
        i = sys.argv.index("--batch-dir")
        batch_dir = sys.argv[i + 1]
        out_path = "data/amarstock_backfill.csv"
        if "--out" in sys.argv:
            out_path = sys.argv[sys.argv.index("--out") + 1]
        run_batch(batch_dir, out_path)
    elif len(sys.argv) >= 3:
        csv_path, run_date = sys.argv[1], sys.argv[2]
        price_out = sys.argv[3] if len(sys.argv) > 3 else f"data/amarstock_prices_{run_date}.csv"
        run_single(csv_path, run_date, price_out)
    else:
        raise SystemExit(
            "Usage:\n"
            "  Single file: python scripts/import_amarstock_csv.py path/to/export.csv YYYY-MM-DD [price_out.csv]\n"
            "  Batch:       python scripts/import_amarstock_csv.py --batch-dir exports/ [--out combined.csv]"
        )
