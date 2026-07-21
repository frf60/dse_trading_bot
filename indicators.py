"""
Pure-pandas technical indicators. No pandas-ta / TA-Lib dependency, so
there's nothing extra to compile or version-pin on a GitHub Actions runner.

v2 (this revision): the old compute_all() took a per-horizon `params` dict
because the v1 model scored 3 horizons separately with different EMA/RSI/
SMA periods. The new model is ONE composite /20 score per stock, so there
is only ONE fixed set of periods now (config.RSI_PERIODS / MACD_PARAMS /
MA_PERIODS / VOL_AVG_PERIOD) — compute_all() reads them straight from
config, no params dict passed in anymore.

ATR and OBV (used by the old score for the "smart_money_entry" point and
for an ATR-based SL fallback) are dropped: the new spec's SL fallback is
a flat % (config.SL_FALLBACK_PCT) and there's no OBV term in the new /20
breakdown. Swing-point support/resistance stays — Part 3 (risk_manager)
still needs it for the SL-quality / Target-quality bonus points.
"""
import pandas as pd
import numpy as np

from config import RSI_PERIODS, MACD_PARAMS, VOL_AVG_PERIOD, MA_PERIODS


def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def sma(series: pd.Series, length: int) -> pd.Series:
    return series.rolling(length).mean()


def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(50)  # neutral value while there's not enough data yet


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = ema(series, fast)
    ema_slow = ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def find_swing_points(df: pd.DataFrame, window: int = 3):
    """
    Returns (swing_lows, swing_highs) — each a pandas Series (indexed by
    date, values are price) of confirmed local extrema: a swing low is a
    bar whose Low is the minimum within `window` bars on EACH side of it
    (needs future bars to confirm, so the most recent `window` bars can
    never be swing points yet — that's expected, not a bug). Swing high is
    the mirror using High. This is a standard "fractal" pivot-point method.
    """
    lows, highs = df["low"], df["high"]
    span = window * 2 + 1
    is_swing_low = lows == lows.rolling(span, center=True).min()
    is_swing_high = highs == highs.rolling(span, center=True).max()
    return lows[is_swing_low.fillna(False)], highs[is_swing_high.fillna(False)]


def nearest_support(df: pd.DataFrame, current_price: float, lookback_days: int,
                     window: int = 3, buffer_pct: float = 0.01):
    """
    The closest confirmed swing-low support below current_price within the
    last `lookback_days` bars, minus a small buffer (so a minor wick right
    at the level doesn't stop things out immediately). Returns None if no
    swing low is found below price in that window — caller (Part 3's
    risk_manager) falls back to the flat SL_FALLBACK_PCT in that case.
    """
    recent = df.tail(lookback_days)
    swing_lows, _ = find_swing_points(recent, window)
    below = swing_lows[swing_lows < current_price]
    if below.empty:
        return None
    closest_support = below.max()  # the highest support still below price = nearest one
    return float(closest_support * (1 - buffer_pct))


def resistance_levels(df: pd.DataFrame, current_price: float, lookback_days: int,
                       window: int = 3) -> list:
    """
    Confirmed swing-high resistance levels above current_price within the
    last `lookback_days` bars, sorted ascending (nearest first). Empty
    list means no resistance found above price in that window — Part 3
    falls back to the pure RRR targets in that case.
    """
    recent = df.tail(lookback_days)
    _, swing_highs = find_swing_points(recent, window)
    above = swing_highs[swing_highs > current_price].sort_values()
    return [float(x) for x in above.tolist()]


def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """
    Attach every indicator the /20 scoring engine needs, on a copy of df.
    df must have columns: high, low, close, volume, indexed oldest -> newest.

    Adds:
      rsi_7d, rsi_14d, rsi_30d   (config.RSI_PERIODS)
      macd_line, signal_line, macd_hist   (config.MACD_PARAMS)
      vol_avg                    (config.VOL_AVG_PERIOD)
      ma_7, ma_14, ma_21          (config.MA_PERIODS)
    """
    out = df.copy()

    for key, period in RSI_PERIODS.items():
        out[f"rsi_{key}"] = rsi(out["close"], period)

    out["macd_line"], out["signal_line"], out["macd_hist"] = macd(
        out["close"], MACD_PARAMS["fast"], MACD_PARAMS["slow"], MACD_PARAMS["signal"]
    )

    out["vol_avg"] = sma(out["volume"], VOL_AVG_PERIOD)

    for p in MA_PERIODS:
        out[f"ma_{p}"] = sma(out["close"], p)

    return out
