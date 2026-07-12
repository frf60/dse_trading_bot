"""
Historical OHLCV, sourced from a Google Sheet ledger instead of scraping
DSE — see README for why (robots.txt) and the daily workflow this expects.

Two tabs:
  RawStaging      — you paste today's DSE price table here (any reasonable
                    tabular paste with a header row; column order doesn't
                    matter, see _match_columns below).
  RawDailyPrices  — canonical ledger: date, ticker, high, low, close, volume.
                    Append-only, deduplicated on (date, ticker). Everything
                    downstream (indicators, scoring, ATR) reads from here.

Note what's NOT required: Open. Every indicator in this project (EMA, RSI,
MACD, SMA, ATR) only needs High/Low/Close/Volume — verify by checking
indicators.py, nothing in it references an "open" column. That's one fewer
number you need to find on whatever page you're copying from.
"""
from datetime import date
import pandas as pd
from sheets_manager import get_tab, read_records, append_rows

RAW_HEADER = ["date", "ticker", "high", "low", "close", "volume"]


def _match_columns(header: list) -> dict:
    """
    Maps this project's required fields to whatever column names are in a
    pasted table, by matching on substrings (case-insensitive) rather than
    exact names — so it survives "Trading Code" vs "Symbol", "Closep" vs
    "Close" vs "LTP", etc. Raises loudly (rather than guessing) if a
    required field can't be found — a wrong silent guess in a price ledger
    is worse than a run that stops and tells you what it saw.
    """
    lowered = [str(h).strip().lower() for h in header]

    def find(*keywords):
        for i, h in enumerate(lowered):
            if any(k in h for k in keywords):
                return i
        return None

    idx = {
        "ticker": find("trading code", "trading_code", "symbol", "code"),
        "high": find("high"),
        "low": find("low"),
        "close": find("closep", "close", "ltp"),  # falls back to LTP if no explicit close col
        "volume": find("volume", "vol"),
    }
    missing = [k for k, v in idx.items() if v is None]
    if missing:
        raise RuntimeError(
            f"Couldn't find columns for {missing} in the pasted header: {header}. "
            "Rename the header cells in RawStaging to include these words, or add "
            "keywords to _match_columns() in sheet_data_source.py."
        )
    return idx


def _clean_number(raw) -> float:
    """Pasted numbers can carry commas ('1,234.50') or stray whitespace."""
    s = str(raw).strip().replace(",", "")
    if s in ("", "-", "—", "N/A", "nan"):
        raise ValueError(f"non-numeric value: {raw!r}")
    return float(s)


def parse_staging_rows(values: list, run_date: str) -> tuple:
    """
    Pure function (no Sheets I/O) so it's unit-testable: takes the raw 2D
    values from RawStaging (header row + data rows) and returns
    (clean_rows, skipped_count). clean_rows are lists matching RAW_HEADER.
    """
    if not values or len(values) < 2:
        return [], 0

    header, data_rows = values[0], values[1:]
    idx = _match_columns(header)

    clean_rows, skipped = [], 0
    for row in data_rows:
        try:
            ticker = str(row[idx["ticker"]]).strip()
            if not ticker:
                skipped += 1
                continue
            high = _clean_number(row[idx["high"]])
            low = _clean_number(row[idx["low"]])
            close = _clean_number(row[idx["close"]])
            volume = _clean_number(row[idx["volume"]])
            clean_rows.append([run_date, ticker, high, low, close, volume])
        except (ValueError, IndexError):
            skipped += 1  # header/subtotal/malformed row — skip, don't crash the run
            continue
    return clean_rows, skipped


def ingest_staging(sheet, run_date: str = None) -> dict:
    """
    Reads RawStaging, appends new (date, ticker) rows to RawDailyPrices
    (skipping ones already present), then clears RawStaging so it's ready
    for tomorrow's paste. Safe to call on an empty staging tab — a no-op.
    """
    run_date = run_date or date.today().isoformat()
    staging_ws = get_tab(sheet, "raw_staging", ["(paste DSE price table here)"])
    values = staging_ws.get_all_values()

    clean_rows, skipped = parse_staging_rows(values, run_date)
    if not clean_rows:
        return {"ingested": 0, "skipped": skipped, "reason": "staging was empty or unparseable"}

    existing = read_records(sheet, "raw_prices", RAW_HEADER)
    existing_keys = {(str(r["date"]), str(r["ticker"])) for r in existing}
    new_rows = [r for r in clean_rows if (r[0], r[1]) not in existing_keys]

    if new_rows:
        append_rows(sheet, "raw_prices", RAW_HEADER, new_rows)
    staging_ws.clear()

    return {"ingested": len(new_rows), "skipped": skipped,
            "duplicates_ignored": len(clean_rows) - len(new_rows)}


_price_ledger_cache = None  # DataFrame, loaded once per process


def _load_price_ledger(sheet, force_reload: bool = False) -> pd.DataFrame:
    """
    Reads RawDailyPrices ONCE per process and caches it in memory.

    Root cause of the quota-exceeded crash: get_historical_data() used to
    call read_records() (a fresh Sheets API read) every time it ran — and
    scan_universe() calls it once per ticker. With ~277 tickers in the A/B
    universe that's 500+ Sheets API reads in a few seconds, blowing well
    past Google's default per-minute read quota. Now the whole ledger is
    read once, here, and every other function in this module filters the
    same in-memory copy.
    """
    global _price_ledger_cache
    if _price_ledger_cache is not None and not force_reload:
        return _price_ledger_cache

    records = read_records(sheet, "raw_prices", RAW_HEADER)
    df = pd.DataFrame(records, columns=RAW_HEADER)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        for col in ("high", "low", "close", "volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["ticker"])

    _price_ledger_cache = df
    return df


def get_historical_data(sheet, ticker: str, days: int = 100) -> pd.DataFrame:
    """
    Columns: high, low, close, volume — indexed by date, oldest -> newest.
    (No 'open' column — see module docstring.)
    """
    from datetime import timedelta
    df = _load_price_ledger(sheet)
    empty = pd.DataFrame(columns=["high", "low", "close", "volume"])
    empty.index = pd.DatetimeIndex([], name="date")
    if df.empty:
        return empty

    cutoff = pd.Timestamp(date.today() - timedelta(days=int(days * 1.6)))
    sub = df[(df["ticker"] == ticker) & (df["date"] >= cutoff)].dropna()
    if sub.empty:
        return empty
    sub = sub.sort_values("date").set_index("date")
    return sub[["high", "low", "close", "volume"]]


def get_live_price(sheet, ticker: str) -> float:
    """
    Most recent close price for `ticker` from RawDailyPrices. Named
    get_live_price to match what state_manager.py's Hold/Sell check calls —
    now that the pipeline runs once daily (no more intraday checks), "live"
    means "the freshest price you've pasted in" rather than a real-time
    quote, so this reads from the same in-memory ledger as everything else
    instead of hitting the Sheets API per ticker.
    """
    hist = get_historical_data(sheet, ticker, days=30)
    if hist.empty:
        raise RuntimeError(f"No price data for {ticker} in RawDailyPrices yet.")
    return float(hist.iloc[-1]["close"])
