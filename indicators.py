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


def compute_all(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """
    Attach every indicator the scoring engine needs, on a copy of df, using
    the horizon-specific periods in `params` (config.INDICATOR_PARAMS[horizon]).
    Column names are generic (ema_fast/ema_slow/rsi/sma/vol_avg) rather than
    baked-in numbers, since what "fast"/"slow" means changes per horizon.

    ATR stays fixed at 14 regardless of horizon — that's Stop Loss sizing
    (risk_manager.py), a separate concern from this trend/momentum scoring.
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
    return out
