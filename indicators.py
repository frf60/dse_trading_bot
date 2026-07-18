"""
Pure-pandas technical indicators. No pandas-ta / TA-Lib dependency, so
there's nothing extra to compile or version-pin on a GitHub Actions runner.

Every function takes/returns pandas Series. `compute_all(df, params)`
expects a DataFrame with columns: high, low, close, volume (no "open" —
nothing here reads it), indexed oldest -> newest, plus a `params` dict
(see config.INDICATOR_PARAMS) giving the horizon-specific periods to use.
"""
import pandas as pd
import numpy as np


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


def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / length, adjust=False).mean()


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """
    On-Balance Volume — a classic "smart money" / accumulation proxy: adds
    the day's volume when price closed up, subtracts it when price closed
    down. OBV rising (especially while price is flat/consolidating) is
    read as quiet accumulation; falling OBV as distribution. No tick-level
    order-flow data is available here, so this is the standard proxy for
    that using only daily OHLCV.
    """
    direction = np.sign(close.diff().fillna(0))
    return (direction * volume).cumsum()


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
    swing low is found below price in that window — caller should fall
    back to a different method (e.g. ATR-based) in that case.
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
    list means no resistance found above price in that window — typically
    because the stock is breaking out to a new high; caller should fall
    back to a standard percentage target in that case.
    """
    recent = df.tail(lookback_days)
    _, swing_highs = find_swing_points(recent, window)
    above = swing_highs[swing_highs > current_price].sort_values()
    return [float(x) for x in above.tolist()]


def compute_all(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """
    Attach every indicator the scoring engine needs, on a copy of df, using
    the horizon-specific periods in `params` (config.INDICATOR_PARAMS[horizon]).
    Column names are generic (ema_fast/ema_slow/rsi/sma/vol_avg) rather than
    baked-in numbers, since what "fast"/"slow" means changes per horizon.

    ATR stays fixed at 14 regardless of horizon — it's now only a Stop Loss
    FALLBACK for when no support level is found (risk_manager.py), a
    separate concern from this trend/momentum scoring.
    """
    out = df.copy()
    out["ema_fast"] = ema(out["close"], params["ema_fast"])
    out["ema_slow"] = ema(out["close"], params["ema_slow"])
    out["rsi"] = rsi(out["close"], params["rsi"])
    out["macd_line"], out["signal_line"], out["macd_hist"] = macd(
        out["close"], params["macd_fast"], params["macd_slow"], params["macd_signal"]
    )
    out["atr14"] = atr(out, 14)
    out["sma"] = sma(out["close"], params["sma"])              # Bollinger-style middle band
    out["vol_avg"] = sma(out["volume"], params["vol_avg"])
    out["obv"] = obv(out["close"], out["volume"])
    out["obv_ma"] = sma(out["obv"], params["obv_ma"])
    return out
