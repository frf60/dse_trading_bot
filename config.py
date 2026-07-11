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
HORIZONS = {
    "7+":  {"sl_atr": 1.5, "t1_atr": 1.5, "t2_atr": 2.5},
    "14+": {"sl_atr": 2.0, "t1_atr": 2.5, "t2_atr": 4.0},
    "30+": {"sl_atr": 3.0, "t1_atr": 4.0, "t2_atr": 7.0},
}
ENTRY_BAND_PCT = 0.005       # +/- 0.5% around close for the entry range
MIN_RRR = 1.5                # reject any setup below this reward:risk ratio

# ---- Watchlist sizes ----
TOP_N_EOD = 5                # per-horizon count at the 3 PM (end-of-day) run
TOP_N_MIDDAY = 2             # combined "running buy" count at the 12:15 PM run

# ---- Google Sheet layout ----
SPREADSHEET_NAME = "DSE_Trading_Engine"   # used only if SPREADSHEET_ID is None
SPREADSHEET_ID = None                      # paste your sheet's ID here (preferred)
TABS = {
    "active_trades": "ActiveTrades",
    "buy": "Buy",
    "hold": "Hold",
    "sell": "Sell",
    "buy_midday": "Buy_Midday",
}

# ---- Calendar ----
MARKET_TZ = "Asia/Dhaka"     # UTC+6, no DST
HOLIDAY_FILE = "holidays.txt"  # one ISO date per line; DSE closures (Eid etc.)
