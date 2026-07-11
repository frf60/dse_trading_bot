"""
Run with: python tests/smoke_test.py  (from the project root)

Generates synthetic OHLCV for a few fake tickers and runs them through
indicators -> scoring -> risk_manager, with NO network calls. This is the
fastest way to confirm the core math works before you touch DSE data or
Google Sheets credentials at all.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from indicators import compute_all
from scoring import score_row
from risk_manager import build_setup, rank_and_filter
from config import HORIZONS, TOP_N_EOD


def make_synthetic_ohlcv(seed: int, n: int = 100, trend: float = 0.0015) -> pd.DataFrame:
    """A mildly-uptrending random walk so some tickers plausibly score well."""
    idx = pd.date_range(end=pd.Timestamp.today(), periods=n, freq="B")
    n = len(idx)  # pandas can return n or n-1 depending on version quirks — stay in sync
    rng = np.random.default_rng(seed)
    returns = rng.normal(loc=trend, scale=0.015, size=n)
    close = 50 * np.cumprod(1 + returns)
    high = close * (1 + rng.uniform(0, 0.01, n))
    low = close * (1 - rng.uniform(0, 0.01, n))
    open_ = close * (1 + rng.normal(0, 0.005, n))
    volume = rng.integers(50_000, 500_000, n).astype(float)
    volume[-5:] *= 1.8  # simulate a recent volume spike on some names
    return pd.DataFrame({"open": open_, "high": high, "low": low,
                          "close": close, "volume": volume}, index=idx)


def main():
    tickers = {"ACI": 1, "SQURPHARMA": 2, "BEXIMCO": 3, "GP": 4, "BATBC": 5}
    scored = []

    print("--- Indicator + scoring sanity check ---")
    for name, seed in tickers.items():
        df = make_synthetic_ohlcv(seed, trend=0.0015 if seed % 2 else -0.0005)
        enriched = compute_all(df)
        curr, prev = enriched.iloc[-1], enriched.iloc[-2]
        result = score_row(curr, prev)
        scored.append({"ticker": name, "close": float(curr["close"]),
                        "atr14": float(curr["atr14"]), "score": result["total"]})
        print(f"{name:12s} close={curr['close']:.2f}  atr14={curr['atr14']:.2f}  "
              f"score={result['total']}/10  breakdown={result['breakdown']}")
        assert 0 <= result["total"] <= 10, "score out of range!"

    print("\n--- Risk manager sanity check (7+ horizon) ---")
    setups = [build_setup(s["ticker"], s["close"], s["atr14"], s["score"], "7+") for s in scored]
    for s in setups:
        print(f"{s['ticker']:12s} entry={s['entry_low']}-{s['entry_high']}  "
              f"SL={s['stop_loss']}  T1={s['target_1']}  T2={s['target_2']}  "
              f"RRR={s['rrr']}  valid={s['valid']}")
        assert s["stop_loss"] < s["close"] < s["target_1"] < s["target_2"], "SL/T1/T2 ordering broken!"

    top = rank_and_filter(setups, TOP_N_EOD)
    print(f"\nTop {len(top)} of {len(setups)} passed the RRR >= 1.5 filter for 7+ horizon.")
    print("\nALL CHECKS PASSED.")


if __name__ == "__main__":
    main()
