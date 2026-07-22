"""
Implements the technical portion of the composite score:
    RSI (9) + MACD (3) + Volume (3) + MA (3) + DSEX relative-strength (1)
    + Low-proximity (4)  =  23
The remaining 2 points — SL-quality (1) + Target-quality (1) — depend on
risk_manager's support/resistance lookup, not on indicators alone, so they
are NOT computed here. scan.py adds them to this module's
`technical_total` to get the final /25 used against config.MIN_SCORE.

v3 CHANGE (this revision): added score_dsex() (broad-index relative
strength, max 1) and score_low_proximity() (distance from the period low,
max 4). technical_max moved from 18 -> 23. score_stock() now takes an
extra `index_positive` argument (bool or None — None means "DSEX data
wasn't available today", and the point defaults to 0 rather than raising).

score_stock(df, index_positive) expects df = indicators.compute_all(hist)
with at least 2 rows — the last two bars (curr/prev) are needed to detect
a same-day MACD signal-line cross and a same-day stock price direction.
`df` is also used in full (not just curr/prev) for the low-proximity
score, since that needs the lowest `low` across the whole history window.
"""
import pandas as pd

from config import (
    RSI_SCORE_TABLE,
    MACD_HIST_BUY_POINT, MACD_HIST_SELL_POINT,
    MACD_CROSS_UP_POINT, MACD_ABOVE_POINT, MACD_BELOW_POINT,
    VOLUME_SCORE_TABLE,
    MA_PERIODS,
    DSEX_RELATIVE_STRENGTH_POINT,
    LOW_PROXIMITY_SCORE_TABLE,
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


def score_dsex(curr, prev, index_positive) -> dict:
    """
    Max 1 — broad-market relative strength.
    index_positive: True if DSEX closed up today, False if down/flat,
    None if DSEX data wasn't available today (defaults the point to 0
    rather than raising, so one missing index row never kills the whole
    day's scan).

    Rule: DSEX up & stock up -> 0 (nothing special, market carried it).
          DSEX down/flat & stock STILL up -> 1 (stock is fighting the tape).
          Anything else (stock down) -> 0.
    """
    if index_positive is None:
        return {"dsex_relative_strength": 0}
    stock_positive = curr["close"] > prev["close"]
    pts = DSEX_RELATIVE_STRENGTH_POINT if (stock_positive and not index_positive) else 0
    return {"dsex_relative_strength": pts}


def score_low_proximity(df: pd.DataFrame, curr) -> dict:
    """
    Max 4 — how close today's close is to the lowest `low` seen anywhere
    in the available history window (df, not just curr/prev). Closer to
    the period low scores higher (see config.LOW_PROXIMITY_SCORE_TABLE).
    """
    period_low = float(df["low"].min())
    if pd.isna(period_low) or period_low <= 0:
        return {"low_proximity": 0}
    pct_above_low = (curr["close"] - period_low) / period_low * 100
    for lo, hi, pts in LOW_PROXIMITY_SCORE_TABLE:
        if lo <= pct_above_low <= hi:
            return {"low_proximity": pts}
    return {"low_proximity": 0}  # shouldn't happen — the table covers 0..100000


def score_stock(df: pd.DataFrame, index_positive=None) -> dict:
    """
    df: output of indicators.compute_all(hist) — needs >= 2 rows.
    index_positive: bool or None — see score_dsex() above. Pass the SAME
    value for every ticker scanned on a given day (scan.py fetches DSEX
    once per run, not once per ticker).

    Returns:
        {
          "technical_total": int,   # 0-23
          "technical_max": 23,
          "breakdown": {...12 individual line items...}
        }
    scan.py adds risk_manager's sl_quality/target_quality (0-2) to
    `technical_total` to get the final score checked against MIN_SCORE (/25).
    """
    if len(df) < 2:
        raise ValueError("score_stock needs at least 2 rows (curr + prev) for the MACD cross check")

    curr, prev = df.iloc[-1], df.iloc[-2]

    breakdown = {}
    breakdown.update(score_rsi(curr))
    breakdown.update(score_macd(curr, prev))
    breakdown.update(score_volume(curr))
    breakdown.update(score_ma(curr))
    breakdown.update(score_dsex(curr, prev, index_positive))
    breakdown.update(score_low_proximity(df, curr))

    return {
        "technical_total": sum(breakdown.values()),
        "technical_max": 23,
        "breakdown": breakdown,
    }
