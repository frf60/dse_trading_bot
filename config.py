"""
Central configuration for the DSE Algorithmic Watchlist Engine.
Edit values here to tune behavior — nothing else should need touching.
"""

# ---- Universe filters ----
ALLOWED_CATEGORIES = {"A", "B"}
EXCLUDED_SECTORS = {"Mutual Funds", "Mutual Fund"}

# ---- Data requirements ----
HISTORY_DAYS = 100          # calendar days of OHLCV pulled per ticker
MIN_BARS_REQUIRED = 55      # minimum trading bars needed to trust EMA50 / ATR14

# ---- Scoring engine weights (sum to 10, per the blueprint) ----
SCORE_WEIGHTS = {
    "price_gt_ema20": 1,
    "price_gt_ema50": 1,
    "ema20_gt_ema50": 1,
    "rsi_healthy": 1,
    "macd_signal_ok": 1,
    "macd_hist_positive": 1,
    "volume_spike": 2,
    "price_gt_sma20": 2,
}
RSI_LOW, RSI_HIGH = 45, 65

# If True: MACD point only awarded on the exact day the line crosses above
# signal (matches the blueprint literally, but is a rare one-day event).
# If False: point awarded any day MACD line is above signal line (a "state"
# rather than a "cross" — more stocks will qualify most days). Flip freely.
STRICT_MACD_CROSS = True

# ---- Risk parameters per holding horizon ----
# Both SL and Targets scale with each stock's own ATR, holding a FIXED
# risk:reward ratio by construction: t2_atr / sl_atr = 3 / 5 / 8 for
# 7+ / 14+ / 30+ ("1:3", "1:5", "1:8"), per your explicit choice after
# seeing the tradeoff: this makes the RRR >= 1.5 filter effectively a
# no-op (every stock has the same fixed RRR at a given horizon, so it can
# never reject anything) — MIN_RRR is left in place below in case you
# ever want to lower one of these ratios under 1.5 in the future, but it
# isn't doing any differentiating work right now. T1 (a closer, partial-
# profit level) isn't something you specified a ratio for, so it's set to
# half of T2's ATR-distance from entry — an assumption, not a request;
# change t1_atr per horizon below if you want it elsewhere.
HORIZONS = {
    "7+":  {"sl_atr": 1.5, "t1_atr": 2.25, "t2_atr": 4.5},    # RRR to T2 = 3
    "14+": {"sl_atr": 2.0, "t1_atr": 5.0,  "t2_atr": 10.0},   # RRR to T2 = 5
    "30+": {"sl_atr": 3.0, "t1_atr": 12.0, "t2_atr": 24.0},   # RRR to T2 = 8
}
ENTRY_BAND_PCT = 0.005       # +/- 0.5% around close for the entry range
MIN_RRR = 1.5                # kept as a floor even though it's now always cleared
MIN_SCORE = 7                # reject any setup scoring below this out of 10 —
                              # the real quality gate now that RRR always passes

# ---- Watchlist sizes ----
TOP_N_EOD = 5                # per-horizon count at the single daily run

# ---- Google Sheet layout ----
SPREADSHEET_NAME = "DSE_Trading_Engine"
SPREADSHEET_ID = "1MX_DorfqYWxKRyl7DxoWvkabW5X4SQ45Xemidou7k8I"   # takes priority over the name above
TABS = {
    "active_trades": "ActiveTrades",
    "buy": "Buy",
    "hold": "Hold",
    "sell": "Sell",
    "raw_staging": "RawStaging",     # paste today's DSE price table here
    "raw_prices": "RawDailyPrices",  # canonical OHLCV ledger, built up daily
}

# ---- Calendar ----
MARKET_TZ = "Asia/Dhaka"     # UTC+6, no DST
HOLIDAY_FILE = "holidays.txt"  # one ISO date per line; DSE closures (Eid etc.)
