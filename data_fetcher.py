"""
Two remaining jobs for this module, both confirmed working:

1. get_ticker_universe() — reads data/dse_categories.csv, a one-time
   human-compiled list of ticker/category/sector (see README). Unaffected
   by any of the robots.txt issues below since it's not scraped on a
   schedule.

2. get_live_price_map() / get_live_price() — live LTP for every DSE
   ticker in one request, from m.bullbd.com's live table. Confirmed
   reachable (not robots.txt-disallowed) by fetching it directly while
   building this. Used for intraday Hold/Sell checks.

Historical OHLCV (60-100 days per ticker, needed for EMA/RSI/MACD/ATR) is
NOT fetched here anymore. dsebd.org's robots.txt disallows automated
access across the pages that would provide it (day_end_archive.php,
data_archive.php, and the latest-share-price pages — all confirmed
directly). That data now comes from sheet_data_source.py instead, backed
by a Google Sheet you populate by pasting DSE's daily table yourself (a
human looking at a public page, not a bot ignoring robots.txt) — see
README for the exact daily workflow.
"""
import pandas as pd
import requests

CATEGORY_CSV = "data/dse_categories.csv"
BULLBD_LIVE_URL = "https://m.bullbd.com/index-normal.php?segment=none&alp=10&sort=c&order=desc&all=all"

_live_price_cache = {}  # populated once per process (i.e. once per scheduled run)


def get_ticker_universe() -> pd.DataFrame:
    """Returns a DataFrame with columns: ticker, category, sector."""
    try:
        df = pd.read_csv(CATEGORY_CSV)
    except FileNotFoundError:
        raise RuntimeError(
            f"{CATEGORY_CSV} not found. Build it once from "
            "https://www.dsebd.org/by_share_category.php (columns: ticker,category,sector) "
            "before running the pipeline."
        )
    required = {"ticker", "category", "sector"}
    if not required.issubset(df.columns):
        raise RuntimeError(f"{CATEGORY_CSV} must have columns: {sorted(required)}")
    return df


def get_live_price_map() -> dict:
    """
    One HTTP request -> {ticker: last_traded_price} for every DSE instrument
    currently trading. Table layout is parsed defensively (matching columns
    by name rather than hardcoding position) since exact column order was
    verified only against the rendered page, not raw HTML.
    """
    resp = requests.get(BULLBD_LIVE_URL, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    tables = pd.read_html(resp.text)
    table = max(tables, key=len)  # the instrument list is the largest table on the page
    table.columns = [str(c).strip().lower() for c in table.columns]

    ticker_col = next((c for c in table.columns if "company" in c or "trading" in c), None)
    price_col = next((c for c in table.columns if "ltp" in c), None)
    if ticker_col is None or price_col is None:
        raise RuntimeError(
            f"Couldn't find ticker/LTP columns in bullbd's table. Found columns: "
            f"{list(table.columns)} — the page layout may have changed; inspect and fix the "
            "column-matching logic above."
        )

    out = {}
    for _, row in table.iterrows():
        ticker = str(row[ticker_col]).strip()
        try:
            out[ticker] = float(row[price_col])
        except (ValueError, TypeError):
            continue
    return out


def get_live_price(ticker: str) -> float:
    """Latest traded price for one ticker, from a cached whole-market snapshot."""
    global _live_price_cache
    if not _live_price_cache:
        _live_price_cache = get_live_price_map()
    if ticker not in _live_price_cache:
        raise RuntimeError(f"{ticker} not found in the live price snapshot.")
    return _live_price_cache[ticker]
