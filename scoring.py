"""
Implements the technical half of the new /20 composite score:
    RSI (9) + MACD (3) + Volume (3) + MA (3)  =  18
The remaining 2 points — SL-quality (1) + Target-quality (1) — depend on
risk_manager's support/resistance lookup (Part 3), not on indicators
alone, so they are NOT computed here. scan.py (Part 4) will add them to
this module's `technical_total` to get the final /20 used against
config.MIN_SCORE.

score_stock(df) expects df = indicators.compute_all(hist) with at least
2 rows — the last two bars (curr/prev) are needed to detect a same-day
MACD signal-line cross.
"""
import pandas as pd

from config import (
    RSI_SCORE_TABLE,
    MACD_HIST_BUY_POINT, MACD_HIST_SELL_POINT,
    MACD_CROSS_UP_POINT, MACD_ABOVE_POINT, MACD_BELOW_POINT,
    VOLUME_SCORE_TABLE,
    MA_PERIODS,
)


def _rsi_tier_score(value: float, table_for_read: dict) -> int:
    """table_for_read is one of RSI_SCORE_TABLE['7d'/'14d'/'30d'] —
    a dict of {(low, high): points}, ranges inclusive both ends."""
    if pd.isna(value):
        return 0
    for (lo, hi), pts in table_for_read.items():
        if lo <= value <= hi:
            return pts
    return 0  # shouldn't happen — the tables cover 0..999


def score_rsi(curr) -> dict:
    """Max 9 = 3 (7d) + 3 (14d) + 3 (30d)."""
    breakdown = {}
    for read_key, table in RSI_SCORE_TABLE.items():
        breakdown[f"rsi_{read_key}"] = _rsi_tier_score(curr[f"rsi_{read_key}"], table)
    return breakdown


def score_macd(curr, prev) -> dict:
    """
    Max 3 = histogram point (0/1) + line-state point (0/1/2).
    Histogram: positive histogram = buy signal, else sell signal.
    Line state: fresh cross-up TODAY (line was <= signal yesterday, is >
    signal today) scores highest; already-above with no fresh cross scores
    less; below signal scores 0.
    """
    hist_point = (MACD_HIST_BUY_POINT if curr["macd_hist"] > 0
                  else MACD_HIST_SELL_POINT)

    crossed_up_today = (prev["macd_line"] <= prev["signal_line"]
                        and curr["macd_line"] > curr["signal_line"])
    if crossed_up_today:
        line_point = MACD_CROSS_UP_POINT
    elif curr["macd_line"] > curr["signal_line"]:
        line_point = MACD_ABOVE_POINT
    else:
        line_point = MACD_BELOW_POINT

    return {"macd_hist": hist_point, "macd_line_state": line_point}


def score_volume(curr) -> dict:
    """Max 3 — today's volume as a multiple of its own 20-day average."""
    vol_avg = curr["vol_avg"]
    if pd.isna(vol_avg) or vol_avg <= 0:
        return {"volume": 0}
    multiple = curr["volume"] / vol_avg
    for lo, hi, pts in VOLUME_SCORE_TABLE:
        if lo <= multiple < hi:
            return {"volume": pts}
    return {"volume": VOLUME_SCORE_TABLE[-1][2]}  # covers the 2x-or-more open-ended bound


def score_ma(curr) -> dict:
    """Max 3 — +1 for each of MA7/MA14/MA21 that price closes above."""
    breakdown = {}
    for p in MA_PERIODS:
        col = f"ma_{p}"
        breakdown[f"ma_{p}"] = (1 if not pd.isna(curr[col]) and curr["close"] > curr[col]
                                 else 0)
    return breakdown


def score_stock(df: pd.DataFrame) -> dict:
    """
    df: output of indicators.compute_all(hist) — needs >= 2 rows.
    Returns:
        {
          "technical_total": int,   # 0-18
          "technical_max": 18,
          "breakdown": {...10 individual line items...}
        }
    scan.py (Part 4) adds risk_manager's sl_quality/target_quality (0-2)
    to `technical_total` to get the final score checked against MIN_SCORE.
    """
    if len(df) < 2:
        raise ValueError("score_stock needs at least 2 rows (curr + prev) for the MACD cross check")

    curr, prev = df.iloc[-1], df.iloc[-2]

    breakdown = {}
    breakdown.update(score_rsi(curr))
    breakdown.update(score_macd(curr, prev))
    breakdown.update(score_volume(curr))
    breakdown.update(score_ma(curr))

    return {
        "technical_total": sum(breakdown.values()),
        "technical_max": 18,
        "breakdown": breakdown,
    }
