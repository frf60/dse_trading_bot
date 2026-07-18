"""
Implements the /10 technical scoring model. Scores the latest bar of an
indicator-enriched DataFrame (output of indicators.compute_all(hist, params)
for a specific horizon's params) — "ema_fast"/"ema_slow"/"rsi"/"sma"/
"vol_avg"/"obv_ma" mean different actual periods depending which horizon's
params were used to compute them, but the scoring logic itself is
identical across horizons EXCEPT the RSI "healthy" range, which also now
varies per horizon (config.RSI_RANGES).
"""
from config import SCORE_WEIGHTS, RSI_RANGES, STRICT_MACD_CROSS


def score_row(curr, prev, horizon: str) -> dict:
    """
    curr, prev: the last two rows (pandas Series) of a compute_all() output —
    `prev` is needed to detect the MACD cross and OBV/histogram direction.
    `horizon`: which of config.RSI_RANGES to apply for the RSI check.
    Returns {"total": int, "breakdown": {...}} so the report can show *why*
    a stock ranked where it did.
    """
    w = SCORE_WEIGHTS
    b = {}

    b["price_gt_ema_fast"] = w["price_gt_ema_fast"] if curr["close"] > curr["ema_fast"] else 0
    b["price_gt_ema_slow"] = w["price_gt_ema_slow"] if curr["close"] > curr["ema_slow"] else 0
    b["ema_fast_gt_slow"] = w["ema_fast_gt_slow"] if curr["ema_fast"] > curr["ema_slow"] else 0

    rsi_low, rsi_high = RSI_RANGES[horizon]
    b["rsi_healthy"] = w["rsi_healthy"] if rsi_low <= curr["rsi"] <= rsi_high else 0

    # MACD: signal-cross (or state, if STRICT_MACD_CROSS is False) AND a
    # rising positive histogram must BOTH hold for this single point —
    # combined into one condition (was two separate points) to make room
    # for smart_money_entry below while keeping the total at /10.
    if STRICT_MACD_CROSS:
        macd_signal_ok = prev["macd_line"] <= prev["signal_line"] and curr["macd_line"] > curr["signal_line"]
    else:
        macd_signal_ok = curr["macd_line"] > curr["signal_line"]
    hist_growing = curr["macd_hist"] > 0 and curr["macd_hist"] > prev["macd_hist"]
    b["macd_bullish"] = w["macd_bullish"] if (macd_signal_ok and hist_growing) else 0

    # "Smart money" proxy: OBV above its own moving average, i.e. volume
    # flow has been net-accumulating recently rather than distributing —
    # the closest read on institutional/large-player activity available
    # from daily OHLCV alone (no tick-level order-flow data here).
    b["smart_money_entry"] = w["smart_money_entry"] if curr["obv"] > curr["obv_ma"] else 0

    b["volume_spike"] = w["volume_spike"] if curr["volume"] > curr["vol_avg"] else 0
    b["price_gt_sma"] = w["price_gt_sma"] if curr["close"] > curr["sma"] else 0

    return {"total": sum(b.values()), "breakdown": b}
