"""
Implements the /10 technical scoring model from the blueprint. Scores the
latest bar of an indicator-enriched DataFrame (output of
indicators.compute_all(hist, params) for a specific horizon's params) —
"ema_fast"/"ema_slow"/"rsi"/"sma"/"vol_avg" mean different actual periods
depending which horizon's params were used to compute them, but the
scoring logic itself is identical across horizons.
"""
from config import SCORE_WEIGHTS, RSI_LOW, RSI_HIGH, STRICT_MACD_CROSS


def score_row(curr, prev) -> dict:
    """
    curr, prev: the last two rows (pandas Series) of a compute_all() output —
    `prev` is needed to detect the MACD cross and histogram growth.
    Returns {"total": int, "breakdown": {...}} so the report can show *why*
    a stock ranked where it did.
    """
    w = SCORE_WEIGHTS
    b = {}

    b["price_gt_ema_fast"] = w["price_gt_ema_fast"] if curr["close"] > curr["ema_fast"] else 0
    b["price_gt_ema_slow"] = w["price_gt_ema_slow"] if curr["close"] > curr["ema_slow"] else 0
    b["ema_fast_gt_slow"] = w["ema_fast_gt_slow"] if curr["ema_fast"] > curr["ema_slow"] else 0

    b["rsi_healthy"] = w["rsi_healthy"] if RSI_LOW <= curr["rsi"] <= RSI_HIGH else 0

    if STRICT_MACD_CROSS:
        macd_ok = prev["macd_line"] <= prev["signal_line"] and curr["macd_line"] > curr["signal_line"]
    else:
        macd_ok = curr["macd_line"] > curr["signal_line"]
    b["macd_signal_ok"] = w["macd_signal_ok"] if macd_ok else 0

    hist_growing = curr["macd_hist"] > 0 and curr["macd_hist"] > prev["macd_hist"]
    b["macd_hist_positive"] = w["macd_hist_positive"] if hist_growing else 0

    b["volume_spike"] = w["volume_spike"] if curr["volume"] > curr["vol_avg"] else 0
    b["price_gt_sma"] = w["price_gt_sma"] if curr["close"] > curr["sma"] else 0

    return {"total": sum(b.values()), "breakdown": b}

