"""
Central configuration for the DSE Algorithmic Watchlist Engine.
Edit values here to tune behavior — nothing else should need touching.
"""

# ---- Universe: trading engine now checks ONLY this fixed list, not the
# whole A/B category — a deliberate narrowing per your explicit request.
# Add/remove tickers freely.
TRADING_WATCHLIST = [
    "PUBALIBANK", "UTTARABANK", "TRUSTBANK", "DHAKABANK", "SOUTHEASTB", "BATBC", "UPGDCL", "MPETROLEUM", "PADMAOIL", "SUMITPOWER", "DUTCHBANGL", "JAMUNABANK", "MTB", "SHAHJABANK", "UNIQUEHRL", "DOREENPWR", "IDLC", "ACMELAB", "ENVOYTEX", "SQUARETEXT", "CONFIDCEM", "DBH", "MALEKSPIN", "MATINSPINN", "SAIHAMTEX", "SAIHAMCOT", "BSRMSTEEL", "UPGDCL", "INDEXAGRO", "WALTONHIL", "APEXFOOT", "ESQUIRENIT", "BXPHARMA", "ARGONDENIM", "GREENDELT", "BSC", "LHB", "PREMIERCEM", "HWAWELLTEX", "MHSML", "SIMTEX", "EHL", "BANKASIA", "ROBI", "NCCBANK",
]

# ---- Universe filters (kept for reference / other scripts, but the
# trading engine itself now scans TRADING_WATCHLIST above, not this) ----
ALLOWED_CATEGORIES = {"A", "B"}
EXCLUDED_SECTORS = {"Mutual Funds", "Mutual Fund"}

# ---- Data requirements ----
HISTORY_DAYS = 100          # calendar days of OHLCV pulled per ticker

# Minimum trading bars needed before a horizon's own indicators are
# trustworthy — roughly 1.3-1.5x the slowest period that horizon uses
# (see INDICATOR_PARAMS below). A ticker with a shorter trading history
# can still qualify for 7+/14+ before it has enough bars for 30+.
MIN_BARS_REQUIRED = {
    "7+":  30,   # needs ema_slow=21, macd_slow=13
    "14+": 40,   # needs ema_slow=26, macd_slow=26
    "30+": 65,   # needs ema_slow=50, macd_slow=39
}

# ---- Horizon-specific indicator periods ----
# Different holding horizons should weight momentum/trend differently: 7+
# day swings need faster-reacting indicators; 30+ day position trades
# should filter out short-term noise with slower, more smoothed ones. The
# SAME ticker can therefore score differently for 7+ than for 30+ — each
# horizon is scored independently, not derived from a shared base score.
INDICATOR_PARAMS = {
    "7+":  {"ema_fast": 9,  "ema_slow": 21, "rsi": 7,  "macd_fast": 6,  "macd_slow": 13, "macd_signal": 5, "vol_avg": 10, "sma": 10, "obv_ma": 10},
    "14+": {"ema_fast": 12, "ema_slow": 26, "rsi": 14, "macd_fast": 12, "macd_slow": 26, "macd_signal": 9, "vol_avg": 15, "sma": 15, "obv_ma": 20},
    "30+": {"ema_fast": 20, "ema_slow": 50, "rsi": 21, "macd_fast": 19, "macd_slow": 39, "macd_signal": 9, "vol_avg": 30, "sma": 30, "obv_ma": 30},
}

# ---- Scoring engine weights (sum to 10) ----
# MACD's signal-cross and rising-histogram checks are combined into ONE
# "macd_bullish" point (was 2 separate points) to make room for
# smart_money_entry (OBV above its own moving average — a rising-OBV /
# accumulation proxy, the closest thing to "smart money" detectable from
# daily OHLCV alone, no tick-level order-flow data being available).
SCORE_WEIGHTS = {
    "price_gt_ema_fast": 1,
    "price_gt_ema_slow": 1,
    "ema_fast_gt_slow": 1,
    "rsi_healthy": 1,
    "macd_bullish": 1,
    "smart_money_entry": 1,
    "volume_spike": 2,
    "price_gt_sma": 2,
}
# RSI "healthy" range varies per horizon. 7+ (4-13 day) stays 50-65. 14+/30+
# tightened from the original 45-65 draft to 50-70: a floor of 45 risked
# capturing stocks still bearish/consolidating on longer timeframes: a 50
# floor keeps a strict bullish bias across every horizon; the ceiling moves
# to 70 on the longer horizons since sustained strength over weeks
# legitimately runs a bit hotter than a 4-13 day swing without necessarily
# being "overbought" in the way it would be on a fast timeframe.
RSI_RANGES = {
    "7+":  (50, 65),   # "4-13 day" tier
    "14+": (50, 70),   # "14-29 day" tier
    "30+": (50, 70),   # "30-60 day" tier
}

# If True: the MACD point only counts on the exact day the line crosses
# above signal (rare, one-day event). If False: counts any day MACD line
# sits above signal (a "state" rather than a "cross" — more stocks
# qualify). Flip freely.
STRICT_MACD_CROSS = True

# ---- Risk parameters per holding horizon ----
# Stop Loss and Targets are now primarily SUPPORT/RESISTANCE based rather
# than pure ATR multiples: SL looks for the nearest confirmed swing-low
# support below entry within sr_lookback_days; Target 1/2 look for the
# nearest two confirmed swing-high resistance levels above entry in the
# same window. Either can fall back when no such level exists nearby:
#   - No support found -> SL falls back to sl_atr * ATR14 below entry
#     (the old pure-ATR method), so a stock with no clear floor still gets
#     a sane stop instead of none at all.
#   - No resistance found (typically because the stock is breaking out to
#     a new high, with nothing above it to reference) -> Target 1/2 fall
#     back to fallback_pct_low / fallback_pct_high above the entry HIGH
#     price. Only one resistance level found (no second one for T2) ->
#     T1 uses that level, T2 uses fallback_pct_high.
# sr_lookback_days scales with horizon — a 30-50 day hold should reference
# support/resistance further back than a 4-13 day one.
# Horizon KEYS are kept as "7+"/"14+"/"30+" (unchanged labels, to avoid a
# risky rename across every file and to keep existing ActiveTrades rows
# readable) but their MEANING now matches your new day-range spec exactly:
#   "7+"  = 4-13 day hold,  3-6% fallback target range
#   "14+" = 14-29 day hold, 7-10% fallback target range
#   "30+" = 30-60 day hold, 11-15% fallback target range
HORIZONS = {
    "7+":  {"sl_atr": 1.5, "sr_lookback_days": 60,  "fallback_pct_low": 0.03, "fallback_pct_high": 0.06},
    "14+": {"sl_atr": 2.0, "sr_lookback_days": 90,  "fallback_pct_low": 0.07, "fallback_pct_high": 0.10},
    "30+": {"sl_atr": 3.0, "sr_lookback_days": 150, "fallback_pct_low": 0.11, "fallback_pct_high": 0.15},
}
SWING_WINDOW = 3             # bars on each side to confirm a swing high/low (see indicators.find_swing_points)
SUPPORT_BUFFER_PCT = 0.01    # SL sits this much below the found support level, not exactly on it
ENTRY_BAND_PCT = 0.005       # +/- 0.5% around close for the entry range
MIN_RRR = 1.5                # SL/Target now genuinely vary per stock (support/resistance-driven),
                              # so this filter has real teeth again, unlike the fixed-ratio design before
MIN_SCORE = 9                # a 9 or 10 out of 10 qualifies now (was strictly
                              # 10 before) — ranking still caps each horizon
                              # at TOP_N_EOD, highest score (then RRR) first

# ---- Watchlist sizes ----
TOP_N_EOD = 2                # per-horizon count at the single daily run

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

# ---- Investment (long-term SIP) watchlist ----
# A separate, simpler system from the daily trading engine above — a fixed
# watchlist of "fundamental" stocks you're accumulating via SIP over 5-20
# years, checked for long-term value entry points (not swing-trade
# signals). Add/remove tickers here freely; the script picks up changes
# automatically next run.
INVESTMENT_WATCHLIST = [
    "BRACBANK", "EBL", "PRIMEBANK", "CITYBANK", "SQURPHARMA", "MARICO", "BERGERPBL", "GP", "JAMUNAOIL", "BSRMLTD",
]
INVESTMENT_RSI_PERIOD = 14          # standard RSI period — distinct from the
                                     # trading engine's horizon-tuned periods above,
                                     # since this is a different kind of signal
INVESTMENT_RSI_MAX = 45             # alert only if RSI <= this
INVESTMENT_LOW_BUFFER_PCT = 0.30    # alert only if price <= all-time-low * (1 + this)
INVESTMENT_MA_MAX_PERIOD = 200      # dynamic: uses min(this, days of history you
                                     # actually have) — a true MA200 once your
                                     # ledger reaches 200 days, an effective
                                     # MA-of-everything-you-have before that
