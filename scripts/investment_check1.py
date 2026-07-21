"""
Investment (long-term SIP) watchlist check — a separate, simpler system
from the daily trading engine, for a fixed watchlist of "fundamental"
stocks (config.INVESTMENT_WATCHLIST) you're accumulating via SIP over
5-20 years.

v2 (this revision, per your explicit answer): a stock qualifies if ANY
ONE (or more) of these 3 rules is true today — this used to require ALL
THREE simultaneously; it's now an OR, not an AND:
  1. RSI(14) is WITHIN config.INVESTMENT_RSI_MIN-INVESTMENT_RSI_MAX
     (31-45), not just "<= 45" — the standard 14-period RSI, a distinct,
     simpler signal from the trading engine's 7/14/30-day reads.
  2. Current close is within INVESTMENT_LOW_BUFFER_PCT (20%, was 30%) of
     the all-time-low-in-dataset. "All-time low" = the lowest LOW ever
     recorded in RawDailyPrices for that ticker — with ~1 year of data
     today this is really "lowest in the data we have" rather than a true
     multi-decade low; it gets more meaningful as the ledger grows daily.
  3. Current close < MA(min(200, days available)) — genuinely dynamic:
     with 90 days of history it's effectively a 90-day MA; once 200+ days
     are on file it becomes a true MA200.

No scoring here (per your answer: "Ekhane scoring kora lagbe na") — this
is a pure rule-based alert. Writes to the Investment sheet tab (cleared
and rewritten each run — it's a current-status board, not a growing
ledger) every watchlist ticker that matches at least one rule, along with
WHICH rule(s) it matched, so the sheet stays self-explanatory without
needing this docstring open next to it.

Reuses sheet_data_source.get_historical_data() (which already caches the
whole RawDailyPrices read once per process) rather than reading the sheet
per ticker.

Run: python scripts/investment_check.py
Needs GOOGLE_SERVICE_ACCOUNT_JSON (reads/writes the Sheet, same as the
rest of the project) — nothing else. No Telegram, no external service.
"""
from datetime import date

from config import (
    INVESTMENT_WATCHLIST, INVESTMENT_RSI_PERIOD,
    INVESTMENT_RSI_MIN, INVESTMENT_RSI_MAX,
    INVESTMENT_LOW_BUFFER_PCT, INVESTMENT_MA_MAX_PERIOD,
)
from sheets_manager import open_sheet, overwrite_tab
from sheet_data_source import get_historical_data
from indicators import rsi

FULL_HISTORY_DAYS = 20000  # effectively "no cutoff" for get_historical_data's date filter
INVESTMENT_HEADER = [
    "ticker", "price", "rsi", "all_time_low", "ma_period", "ma_value",
    "matched_rules", "date_checked",
]


def check_ticker(sheet, ticker: str):
    """Returns a match dict if AT LEAST ONE of the 3 rules holds, else None."""
    hist = get_historical_data(sheet, ticker, days=FULL_HISTORY_DAYS)
    if len(hist) < INVESTMENT_RSI_PERIOD:
        return None  # not enough data yet for a meaningful RSI

    rsi_series = rsi(hist["close"], INVESTMENT_RSI_PERIOD)
    current_rsi = float(rsi_series.iloc[-1])
    current_price = float(hist["close"].iloc[-1])
    all_time_low = float(hist["low"].min())

    ma_period = min(INVESTMENT_MA_MAX_PERIOD, len(hist))
    ma_value = float(hist["close"].tail(ma_period).mean())

    cond_rsi = INVESTMENT_RSI_MIN <= current_rsi <= INVESTMENT_RSI_MAX
    cond_low = current_price <= all_time_low * (1 + INVESTMENT_LOW_BUFFER_PCT)
    cond_ma = current_price < ma_value

    matched = []
    if cond_rsi:
        matched.append(f"RSI {INVESTMENT_RSI_MIN}-{INVESTMENT_RSI_MAX}")
    if cond_low:
        matched.append(f"Within {int(INVESTMENT_LOW_BUFFER_PCT * 100)}% of low")
    if cond_ma:
        matched.append(f"Below MA{ma_period}")

    if not matched:
        return None

    return {
        "ticker": ticker,
        "price": current_price,
        "rsi": round(current_rsi, 1),
        "all_time_low": all_time_low,
        "ma_period": ma_period,
        "ma_value": round(ma_value, 2),
        "matched_rules": ", ".join(matched),
    }


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
            print(f"  MATCH: {result['ticker']} — {result['matched_rules']}")
        else:
            print(f"  no match: {ticker}")

    rows = [[
        m["ticker"], m["price"], m["rsi"], m["all_time_low"],
        m["ma_period"], m["ma_value"], m["matched_rules"], run_date,
    ] for m in matches]
    overwrite_tab(sheet, "investment", INVESTMENT_HEADER, rows)
    print(f"[{run_date}] Investment tab updated: {len(rows)} of "
          f"{len(INVESTMENT_WATCHLIST)} watchlist ticker(s) matched at "
          f"least one rule.")


if __name__ == "__main__":
    main()
