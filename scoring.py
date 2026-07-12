"""
Implements the /10 technical scoring model from the blueprint. Scores the
latest bar of an indicator-enriched DataFrame (output of indicators.compute_all).
"""
from config import SCORE_WEIGHTS, RSI_LOW, RSI_HIGH, STRICT_MACD_CROSS


def score_row(curr, prev) -> dict:
    """
    curr, prev: the last two rows (pandas Series) of compute_all() output —
    `prev` is needed to detect the MACD cross and histogram growth.
    Returns {"total": int, "breakdown": {...}} so the report can show *why*
    a stock ranked where it did.
    """
    w = SCORE_WEIGHTS
    b = {}

    b["price_gt_ema20"] = w["price_gt_ema20"] if curr["close"] > curr["ema20"] else 0
    b["price_gt_ema50"] = w["price_gt_ema50"] if curr["close"] > curr["ema50"] else 0
    b["ema20_gt_ema50"] = w["ema20_gt_ema50"] if curr["ema20"] > curr["ema50"] else 0

    b["rsi_healthy"] = w["rsi_healthy"] if RSI_LOW <= curr["rsi14"] <= RSI_HIGH else 0

    if STRICT_MACD_CROSS:
        macd_ok = prev["macd_line"] <= prev["signal_line"] and curr["macd_line"] > curr["signal_line"]
    else:
        macd_ok = curr["macd_line"] > curr["signal_line"]
    b["macd_signal_ok"] = w["macd_signal_ok"] if macd_ok else 0

    hist_growing = curr["macd_hist"] > 0 and curr["macd_hist"] > prev["macd_hist"]
    b["macd_hist_positive"] = w["macd_hist_positive"] if hist_growing else 0

    b["volume_spike"] = w["volume_spike"] if curr["volume"] > curr["vol_sma20"] else 0
    b["price_gt_sma20"] = w["price_gt_sma20"] if curr["close"] > curr["sma20"] else 0

    return {"total": sum(b.values()), "breakdown": b}
