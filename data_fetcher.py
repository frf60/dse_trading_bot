"""
DSE data ingestion layer.

IMPORTANT - READ BEFORE DEPLOYING:
There is no free official real-time DSE API. This module is built on
`bdshare` (https://pypi.org/project/bdshare/), a third-party open-source
scraper of dsebd.org. That means:

  1. It is NOT an official/guaranteed data feed. dsebd.org can change its
     page structure at any time and silently break this — it hasn't been
     verified from this environment (no internet access in the sandbox
     this was built in). Test it manually the moment you deploy.
  2. You're responsible for checking DSE's terms of use around automated
     access before running this on a schedule, and for keeping request
     rates polite (this module sleeps between calls).
  3. If bdshare breaks, replace the bodies of the functions below with a
     direct scraper against dsebd.org's own pages — the function
     signatures are the contract the rest of the pipeline relies on, so
     nothing else needs to change.

Category/sector source of truth:
  bdshare's live snapshot doesn't reliably expose category (A/B/N/Z) and
  sector for every ticker across versions. The recommended approach is to
  scrape https://www.dsebd.org/by_share_category.php ONCE, save it as
  data/dse_categories.csv, and refresh it weekly (categories rarely
  change) rather than hitting it on every run. get_ticker_universe() below
  reads from that CSV.
"""
import time
from datetime import date, timedelta
import pandas as pd

try:
    import bdshare
    HAS_BDSHARE = True
except ImportError:
    HAS_BDSHARE = False

CATEGORY_CSV = "data/dse_categories.csv"


def get_ticker_universe() -> pd.DataFrame:
    """
    Returns a DataFrame with columns: ticker, category, sector.
    Reads from CATEGORY_CSV — see module docstring for how to build it.
    """
    try:
        df = pd.read_csv(CATEGORY_CSV)
    except FileNotFoundError:
        raise RuntimeError(
            f"{CATEGORY_CSV} not found. Scrape https://www.dsebd.org/by_share_category.php "
            "once and save ticker,category,sector columns there before running the pipeline."
        )
    required = {"ticker", "category", "sector"}
    if not required.issubset(df.columns):
        raise RuntimeError(f"{CATEGORY_CSV} must have columns: {sorted(required)}")
    return df


def get_historical_data(ticker: str, days: int = 100) -> pd.DataFrame:
    """Fetch `days` of OHLCV for one ticker. Columns: open, high, low, close, volume."""
    if not HAS_BDSHARE:
        raise RuntimeError("bdshare is not installed. pip install bdshare")
    end = date.today()
    start = end - timedelta(days=int(days * 1.6))  # buffer for weekends/holidays
    df = bdshare.get_hist_data(str(start), str(end), ticker)
    time.sleep(1)  # be polite to the source
    df = df.rename(columns=str.lower)
    return df[["open", "high", "low", "close", "volume"]].sort_index()


def get_live_price(ticker: str) -> float:
    """Latest traded price for one ticker — used by the state manager for Hold/Sell checks."""
    if not HAS_BDSHARE:
        raise RuntimeError("bdshare is not installed. pip install bdshare")
    df = bdshare.get_current_trade_data(ticker)
    time.sleep(0.5)
    return float(df["LTP"].iloc[0])
