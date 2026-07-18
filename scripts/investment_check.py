"""
Investment (long-term SIP) watchlist check — a separate, simpler system
from the daily trading engine, for a fixed watchlist of "fundamental"
stocks (config.INVESTMENT_WATCHLIST) you're accumulating via SIP over
5-20 years.

Writes to the Investment sheet tab (cleared and rewritten each run — it's
a current-status board, not a growing ledger) whichever watchlist tickers
have ALL THREE hold simultaneously, as of today:
  1. RSI(14) <= INVESTMENT_RSI_MAX (default 45) — the standard 14-period
     RSI, not the trading engine's horizon-tuned periods; a distinct,
     simpler signal for long-term value entries.
  2. Current close <= all-time-low-in-dataset * (1 + INVESTMENT_LOW_BUFFER_PCT).
     "All-time low" = the lowest LOW ever recorded in RawDailyPrices for
     that ticker. With ~1 year of data today, this is really "lowest in
     the data we have" rather than a true multi-decade all-time low — it
     gets more meaningful as your ledger grows daily, automatically.
  3. Current close < MA(min(200, days available)) — genuinely dynamic:
     with 90 days of history it's effectively a 90-day MA; once you have
     200+ days it becomes a true MA200.

Reuses sheet_data_source.get_historical_data() (which already caches the
whole RawDailyPrices read once per process) rather than reading the sheet
per ticker — 15 tickers read one-by-one would otherwise repeat the exact
Sheets-API quota problem this project already hit and fixed once.

Run: python scripts/investment_check.py
Needs GOOGLE_SERVICE_ACCOUNT_JSON (reads/writes the Sheet, same as the
rest of the project) — nothing else. No Telegram, no external service.
"""
from datetime import date

from config import (
    INVESTMENT_WATCHLIST, INVESTMENT_RSI_PERIOD, INVESTMENT_RSI_MAX,
    INVESTMENT_LOW_BUFFER_PCT, INVESTMENT_MA_MAX_PERIOD,
)
from sheets_manager import open_sheet, overwrite_tab
from sheet_data_source import get_historical_data
from indicators import rsi

FULL_HISTORY_DAYS = 20000  # effectively "no cutoff" for get_historical_data's date filter
INVESTMENT_HEADER = ["ticker", "price", "rsi", "all_time_low", "ma_period", "ma_value", "date_checked"]


def check_ticker(sheet, ticker: str):
    """Returns a match dict if all 3 conditions hold, else None."""
    hist = get_historical_data(sheet, ticker, days=FULL_HISTORY_DAYS)
    if len(hist) < INVESTMENT_RSI_PERIOD:
        return None  # not enough data yet for a meaningful RSI

    rsi_series = rsi(hist["close"], INVESTMENT_RSI_PERIOD)
    current_rsi = float(rsi_series.iloc[-1])
    current_price = float(hist["close"].iloc[-1])
    all_time_low = float(hist["low"].min())

    ma_period = min(INVESTMENT_MA_MAX_PERIOD, len(hist))
    ma_value = float(hist["close"].tail(ma_period).mean())

    cond_rsi = current_rsi <= INVESTMENT_RSI_MAX
    cond_price = current_price <= all_time_low * (1 + INVESTMENT_LOW_BUFFER_PCT)
    cond_ma = current_price < ma_value

    if cond_rsi and cond_price and cond_ma:
        return {
            "ticker": ticker,
            "price": current_price,
            "rsi": round(current_rsi, 1),
            "all_time_low": all_time_low,
            "ma_period": ma_period,
            "ma_value": round(ma_value, 2),
        }
    return None


def main():
    run_date = date.today().isoformat()
    sheet = open_sheet()

    matches = []
    for ticker in INVESTMENT_WATCHLIST:
        try:
            result = check_ticker(sheet, ticker)
        except Exception as e:
            print(f"  [skip] {ticker}: {e}")
            continue
        if result:
            matches.append(result)
            print(f"  MATCH: {result}")
        else:
            print(f"  no match: {ticker}")

    rows = [[
        m["ticker"], m["price"], m["rsi"], m["all_time_low"],
        m["ma_period"], m["ma_value"], run_date,
    ] for m in matches]
    overwrite_tab(sheet, "investment", INVESTMENT_HEADER, rows)
    print(f"[{run_date}] Investment tab updated: {len(rows)} of {len(INVESTMENT_WATCHLIST)} "
          f"watchlist ticker(s) currently meet all 3 conditions.")


if __name__ == "__main__":
    main()
