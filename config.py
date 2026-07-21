"""
Central configuration for the DSE Algorithmic Watchlist Engine.
Edit values here to tune behavior — nothing else should need touching.

v2 (this revision): moved from a per-horizon /10 score + 2-target model to
a SINGLE composite /20 score per stock, with 3 INDEPENDENT targets (T1/T2/T3)
tracked off ONE entry. "Horizon" now only labels an expected time-to-hit
window shown in the sheet (T1 ~3-13 days, T2 ~14-29 days, T3 ~30+ days) —
it no longer changes which indicator periods are used for scoring.
"""

# ---- Trading list (technical /20 scoring + T1/T2/T3 setups) ----
# Add/remove tickers freely, any time.
TRADING_WATCHLIST = [
    "PUBALIBANK", "UTTARABANK", "TRUSTBANK", "DHAKABANK", "SOUTHEASTB",
    "BATBC", "MPETROLEUM", "PADMAOIL", "SUMITPOWER", "DUTCHBANGL",
    "JAMUNABANK", "MTB", "SHAHJABANK", "UNIQUEHRL", "DOREENPWR",
    "IDLC", "ACMELAB", "ENVOYTEX", "SQUARETEXT", "CONFIDCEM",
    "DBH", "MALEKSPIN", "MATINSPINN", "SAIHAMTEX", "SAIHAMCOT",
    "BSRMSTEEL", "UPGDCL", "INDEXAGRO", "WALTONHIL", "APEXFOOT",
    "ESQUIRENIT", "BXPHARMA", "ARGONDENIM", "GREENDELT", "BSC",
    "LHB", "PREMIERCEM", "HWAWELLTEX", "MHSML", "SIMTEX",
    "EHL", "BANKASIA", "ROBI", "NCCBANK",
]

# ---- Investment (long-term SIP) watchlist — no scoring, rule-based alert only ----
INVESTMENT_WATCHLIST = [
    "SQURPHARMA", "MARICO", "BERGERPBL", "GP", "JAMUNAOIL",
    "BSRMLTD", "BRACBANK", "EBL", "PRIMEBANK", "CITYBANK",
]

# ---- Universe filters (kept for reference / other scripts only) ----
ALLOWED_CATEGORIES = {"A", "B"}
EXCLUDED_SECTORS = {"Mutual Funds", "Mutual Fund"}

# ---- Data requirements ----
HISTORY_DAYS = 120          # calendar days of OHLCV pulled per ticker
# Single bar-count floor now (scoring is no longer split per horizon).
# Needs to cover the slowest input: RSI-30, MACD(12,26,9), MA-21, vol-avg-20.
MIN_BARS_REQUIRED = 45

# ---- Indicator periods (fixed, shared by every stock/every score) ----
RSI_PERIODS = {"7d": 7, "14d": 14, "30d": 30}   # 3 separate RSI reads, scored independently
MACD_PARAMS = {"fast": 12, "slow": 26, "signal": 9}
VOL_AVG_PERIOD = 20
MA_PERIODS = [7, 14, 21]

# ---- Scoring engine: single composite score, /20 total ----
# RSI (9) + MACD (3) + Volume (3) + MA (3) + SL-quality (1) + Target-quality (1) = 20
SCORE_MAX = 20
MIN_SCORE = 10   # only stocks scoring >=10/20 are eligible for the daily Buy pick

# RSI tiers -> points, PER horizon-read. Ranges are inclusive both ends:
# (0-30, 31-45, 46-57, 58-69, 70+) each mapped to a score for that read.
RSI_SCORE_TABLE = {
    "7d":  {(0, 30): 0, (31, 45): 1, (46, 57): 2, (58, 69): 3, (70, 999): 0},
    "14d": {(0, 30): 0, (31, 45): 1, (46, 57): 3, (58, 69): 2, (70, 999): 0},
    "30d": {(0, 30): 0, (31, 45): 3, (46, 57): 2, (58, 69): 1, (70, 999): 0},
}
RSI_MAX_SCORE = 9   # 3 + 3 + 3

# MACD (max 3) = histogram check (0 or 1) + line-vs-signal state (0, 1, or 2)
MACD_HIST_BUY_POINT = 1     # histogram shows a buy signal (positive & rising)
MACD_HIST_SELL_POINT = 0
MACD_CROSS_UP_POINT = 2     # macd line crosses from below to above signal line, TODAY
MACD_ABOVE_POINT = 1        # macd line already above signal line (no fresh cross)
MACD_BELOW_POINT = 0        # macd line below signal line
MACD_MAX_SCORE = 3

# Volume vs its own 20-day average
VOLUME_SCORE_TABLE = [
    # (multiple_of_avg_lower_bound, multiple_of_avg_upper_bound, score)
    (0.0, 1.0, 0),    # below 20-day average
    (1.0, 1.5, 1),    # at/above average but below 1.5x
    (1.5, 2.0, 2),    # at/above 1.5x but below 2x
    (2.0, float("inf"), 3),  # 2x or more
]
VOLUME_MAX_SCORE = 3

# MA (max 3): +1 for each of price>MA7, price>MA14, price>MA21
MA_MAX_SCORE = 3

# SL / Target "quality" bonus points — these depend on risk_manager's own
# support/resistance lookup (computed in Part 3), NOT on indicators alone.
SL_SUPPORT_POINT = 1     # stop loss placed on real support
SL_FALLBACK_POINT = 0    # stop loss is the flat 6% fallback
TARGET_RESISTANCE_POINT = 1   # at least one target placed on real resistance
TARGET_FALLBACK_POINT = 0     # all targets are RRR/% fallback

# ---- Risk parameters: ONE entry, THREE independent targets ----
# Targets are pure RRR multiples off entry_high (per your explicit answer),
# NOT horizon-specific percentages anymore. "Horizon" below is a DISPLAY
# label only (expected days-to-hit shown in the sheet), it does not change
# how T1/T2/T3 are calculated.
TARGET_RRR = {
    "target_1": 1.0,
    "target_2": 1.5,
    "target_3": 2.0,
}
TARGET_HORIZON_LABEL = {
    "target_1": "3-13 din (7+)",
    "target_2": "14-29 din (14+)",
    "target_3": "30+ din",
}

ENTRY_BAND_PCT = 0.005        # +/- 0.5% around close for the entry range
SWING_WINDOW = 3               # bars each side to confirm a swing high/low
SR_LOOKBACK_DAYS = 90          # bars scanned for support/resistance
SUPPORT_BUFFER_PCT = 0.01      # SL sits this much below the found support level

# Stop loss: use nearest real support if found, else flat 6% below entry_high
SL_FALLBACK_PCT = 0.06

# A resistance level closer than this to entry_high isn't a usable target
MIN_TARGET_BUFFER_PCT = 0.03

# ---- Watchlist sizes ----
TOP_N_DAILY = 5   # highest-scoring NEW buys added per day, across the WHOLE trading list

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
    "investment": "Investment",      # today's fundamental-watchlist matches, rewritten daily
}

# ---- Calendar ----
MARKET_TZ = "Asia/Dhaka"     # UTC+6, no DST
HOLIDAY_FILE = "holidays.txt"  # one ISO date per line; DSE closures (Eid etc.)

# ---- Investment (long-term SIP) watchlist rules ----
# A stock shows up in the Investment tab if ANY ONE of these 3 is true.
# No scoring here — pure rule-based alert.
INVESTMENT_RSI_PERIOD = 14
INVESTMENT_RSI_MIN = 31          # rule 1: RSI must be WITHIN 31-45 (not just <=45)
INVESTMENT_RSI_MAX = 45
INVESTMENT_LOW_BUFFER_PCT = 0.20  # rule 2: price within 20% of the all-time low seen in uploaded history
INVESTMENT_MA_MAX_PERIOD = 200    # rule 3: price below MA(min(200, days of history available))
