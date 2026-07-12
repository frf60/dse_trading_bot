"""
Turns AmarStock "Latest Share Price" / "CSV Data Download" exports into
what this project needs. Two modes:

  Single file (today's export, or one historical date):
    python scripts/import_amarstock_csv.py path/to/export.csv 2026-07-12

  Batch (a folder of historical exports, for backfilling —
  amarstock.com/csv-data-download offers "DSE eod CSV data for any date",
  so you can pull ~60-100 past trading days this way instead of waiting
  2-3 months of daily pastes to clear MIN_BARS_REQUIRED):
    python scripts/import_amarstock_csv.py --batch-dir exports/ --out data/amarstock_backfill.csv
  Each file in the folder must have its date somewhere in the filename
  (YYYY-MM-DD, e.g. "2026-05-01.csv" or "AmarStock-2026-05-01.csv").

Either mode writes:
1. data/dse_categories.csv (ticker, category, sector) — AmarStock's "CAT"
   column gives the official A/B/N/Z/Y classification directly. Mutual
   funds/bonds/sukuk don't have an explicit sector label in this export,
   but reliably have a blank MARKET CAP (verified: 45 rows, spanning
   obviously-named funds like "ABB1STMF" and less obvious ones like
   "GRAMEENS2", "ICBAGRANI1", "RELIANCE1", plus bonds/sukuk like
   "APSCLBOND", "BEXGSUKUK") — tagged sector="Mutual Funds" so the
   existing EXCLUDED_SECTORS filter in config.py catches them as-is.
   In batch mode, built from the most recent file (categories barely
   change day to day).
2. A backfill-ready price CSV (date, ticker, high, low, close, volume) —
   feed straight into scripts/backfill_from_csv.py. Rows with no traded
   price (suspended/non-trading tickers, bonds) are dropped.

AmarStock's column names ("TRADING CODE", "High", "Low", "Close",
"Volume") already match sheet_data_source.py's paste parser, so any of
these files can also be pasted directly into the RawStaging tab as a
daily update instead of copying an HTML table by hand.
"""
import re
import sys
import glob
import os
import pandas as pd

CATEGORY_OUT = "data/dse_categories.csv"
FUND_SECTOR_LABEL = "Mutual Funds"  # matches config.EXCLUDED_SECTORS exactly
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def build_category_csv(df: pd.DataFrame, out_path: str = CATEGORY_OUT):
    is_fund_or_bond = df["MARKET CAP"].isna()
    cats = pd.DataFrame({
        "ticker": df["TRADING CODE"].str.strip(),
        "category": df["CAT"].str.strip(),
        "sector": is_fund_or_bond.map({True: FUND_SECTOR_LABEL, False: ""}),
    })
    # Structurally-corrupted rows (e.g. a bond whose columns shifted in the
    # export, CAT showing "-") — drop rather than guess.
    cats = cats[cats["category"].isin(["A", "B", "N", "Z", "Y"])]
    cats.to_csv(out_path, index=False)
    return cats


def build_price_rows(df: pd.DataFrame, run_date: str) -> pd.DataFrame:
    numeric = df.copy()
    for col in ("High", "Low", "Close", "Volume"):
        numeric[col] = pd.to_numeric(numeric[col], errors="coerce")
    numeric = numeric.dropna(subset=["High", "Low", "Close", "Volume"])
    return pd.DataFrame({
        "date": run_date,
        "ticker": numeric["TRADING CODE"].str.strip(),
        "high": numeric["High"],
        "low": numeric["Low"],
        "close": numeric["Close"],
        "volume": numeric["Volume"],
    })


def run_single(csv_path: str, run_date: str, price_out_path: str):
    df = pd.read_csv(csv_path)
    cats = build_category_csv(df)
    prices = build_price_rows(df, run_date)
    prices.to_csv(price_out_path, index=False)

    ab_count = cats[cats["category"].isin(["A", "B"])].shape[0]
    fund_count = (cats["sector"] == FUND_SECTOR_LABEL).sum()
    print(f"Categories: {len(cats)} tickers written to {CATEGORY_OUT} "
          f"({ab_count} in category A/B, {fund_count} tagged as funds/bonds).")
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
        except Exception as e:
            skipped_files.append((path, str(e)))
            continue
        all_prices.append(build_price_rows(df, run_date))
        if latest_date is None or run_date > latest_date:
            latest_date, latest_df = run_date, df

    if not all_prices:
        raise SystemExit("No usable files found — check filenames contain YYYY-MM-DD.")

    combined = pd.concat(all_prices, ignore_index=True)
    combined = combined.drop_duplicates(subset=["date", "ticker"])
    combined.to_csv(out_path, index=False)

    cats = build_category_csv(latest_df)
    ab_count = cats[cats["category"].isin(["A", "B"])].shape[0]

    print(f"Processed {len(files) - len(skipped_files)}/{len(files)} files "
          f"covering {combined['date'].nunique()} trading days, "
          f"{combined['ticker'].nunique()} distinct tickers.")
    print(f"Combined price rows written to {out_path} — feed this into "
          f"scripts/backfill_from_csv.py next.")
    print(f"Categories refreshed from {latest_date}'s file: {len(cats)} tickers "
          f"({ab_count} in category A/B).")
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
