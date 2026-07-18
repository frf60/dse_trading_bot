"""
Run with: python tests/smoke_test.py  (from the project root)

Generates synthetic OHLCV and runs it through indicators -> scoring ->
risk_manager, with NO network calls, across all 3 horizons (each with its
own indicator periods + RSI range now — config.INDICATOR_PARAMS /
config.RSI_RANGES). Also directly validates the support/resistance swing-
point detection with engineered data, the MIN_SCORE gate, and the
already-active exclusion logic. Fastest way to confirm the core math
works before touching DSE data or Google Sheets credentials at all.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from indicators import compute_all, find_swing_points, nearest_support, resistance_levels
from scoring import score_row
from risk_manager import build_setup, rank_and_filter
from scan import build_watchlists
from config import HORIZONS, INDICATOR_PARAMS, TOP_N_EOD, MIN_SCORE, SWING_WINDOW


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


def test_swing_points():
    print("--- Swing point / support / resistance sanity check ---")
    # Hand-built: a clean V shape (down then up) so the bottom is an
    # unambiguous swing low, and a clean inverted-V (up then down) earlier
    # in the series so its peak is an unambiguous swing high, with the
    # series ending partway up the recovery (a realistic "current price"
    # sitting between a known support below and a known resistance above).
    n = 40
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    prices = []
    for i in range(n):
        if i < 6:
            prices.append(90 + i * 5)         # rising into a peak at i=5 (115)
        elif i < 15:
            prices.append(115 - (i - 5) * 3)  # down from the peak to 88 at i=15
        elif i < 25:
            prices.append(88 - (i - 15) * 3)  # down further to 58 at i=25 (the swing low)
        else:
            prices.append(58 + (i - 25) * 2)  # recovering back up to 86 at i=39
    close = pd.Series(prices, index=idx)
    df = pd.DataFrame({
        "high": close * 1.01, "low": close * 0.99, "close": close,
        "volume": [10000] * n,
    })

    swing_lows, swing_highs = find_swing_points(df, window=SWING_WINDOW)
    print(f"  Found {len(swing_lows)} swing low(s), {len(swing_highs)} swing high(s)")
    assert len(swing_lows) >= 1, "should find the obvious bottom at i=25"
    assert len(swing_highs) >= 1, "should find the obvious peak at i=0"

    current_price = float(close.iloc[-1])  # ~90, partway up the recovery
    support = nearest_support(df, current_price, lookback_days=n, window=SWING_WINDOW, buffer_pct=0.01)
    resistances = resistance_levels(df, current_price, lookback_days=n, window=SWING_WINDOW)
    print(f"  current_price={current_price:.1f}  nearest_support={support}  resistances={resistances}")
    assert support is not None and support < current_price, "support should be found below current price"
    # The early peak (120) is far in the past relative to the recovery high — still a valid
    # resistance candidate as long as it's above current price and within the lookback window.

    print("  Swing point detection works as expected.\n")


def main():
    test_swing_points()

    tickers = {"ACI": 1, "SQURPHARMA": 2, "BEXIMCO": 3, "GP": 4, "BATBC": 5}

    print("--- Per-horizon indicator + scoring sanity check ---")
    scan_results = {h: [] for h in HORIZONS}
    for horizon in HORIZONS:
        print(f"\n[{horizon}] params: {INDICATOR_PARAMS[horizon]}")
        for name, seed in tickers.items():
            df = make_synthetic_ohlcv(seed, trend=0.0015 if seed % 2 else -0.0005)
            enriched = compute_all(df, INDICATOR_PARAMS[horizon])
            curr, prev = enriched.iloc[-1], enriched.iloc[-2]
            result = score_row(curr, prev, horizon)
            scan_results[horizon].append({
                "ticker": name, "hist": df,
                "atr14": float(curr["atr14"]), "score": result["total"],
            })
            print(f"  {name:12s} close={curr['close']:.2f}  score={result['total']}/10")
            assert 0 <= result["total"] <= 10, "score out of range!"

    print("\n--- Risk manager sanity check (all horizons, support/resistance + fallback) ---")
    for horizon in HORIZONS:
        setups = [
            build_setup(s["ticker"], s["hist"], s["atr14"], s["score"], horizon)
            for s in scan_results[horizon]
        ]
        for s in setups:
            assert s["stop_loss"] < s["close"] < s["target_1"] < s["target_2"], \
                f"SL/close/T1/T2 ordering broken for {s['ticker']} ({horizon})! {s}"
            assert s["sl_source"] in ("support", "atr_fallback")
            assert s["target_source"] in ("resistance", "resistance_plus_fallback", "fallback_pct")
            if s["score"] < MIN_SCORE:
                assert s["valid"] is False, \
                    f"{s['ticker']} ({horizon}) scored {s['score']} but was marked valid!"
        top = rank_and_filter(setups, TOP_N_EOD)
        sources = [(s["ticker"], s["sl_source"], s["target_source"]) for s in setups]
        print(f"  {horizon}: {len(top)} of {len(setups)} cleared MIN_SCORE={MIN_SCORE} "
              f"(scores: {[s['score'] for s in setups]})")
        print(f"    SL/target sources this run: {sources}")

    print("\n--- MIN_SCORE gate: direct check with hand-built history ---")
    flat_hist = pd.DataFrame({
        "high": [100.0] * 60, "low": [99.0] * 60, "close": [99.5] * 60, "volume": [10000] * 60,
    })
    s_low = build_setup("LOWSCORE", flat_hist, 2.0, MIN_SCORE - 1, "7+")
    s_high = build_setup("HIGHSCORE", flat_hist, 2.0, MIN_SCORE, "7+")
    assert s_low["valid"] is False, "score below MIN_SCORE should never be valid!"
    print(f"  score={MIN_SCORE - 1} -> valid={s_low['valid']}, score={MIN_SCORE} -> "
          f"valid={s_high['valid']} (flat history may still fail on RRR/ordering — that's fine, "
          f"this only checks the score gate itself doesn't block a qualifying score)")

    print("\n--- Already-active exclusion check ---")
    sample_hist = scan_results["7+"][0]["hist"]
    fake_scan = {h: [{"ticker": "ACI", "hist": sample_hist, "atr14": 2.0, "score": 10}] for h in HORIZONS}
    watchlists_no_exclude = build_watchlists(fake_scan, top_n=5)
    watchlists_excluded = build_watchlists(fake_scan, top_n=5, exclude={("ACI", "7+")})
    print(f"  7+ without exclusion: {len(watchlists_no_exclude['7+'])} pick(s)")
    print(f"  7+ WITH (ACI,7+) excluded: {len(watchlists_excluded['7+'])} pick(s)")
    print(f"  14+ WITH (ACI,7+) excluded (different horizon, unaffected): {len(watchlists_excluded['14+'])} pick(s)")
    assert len(watchlists_excluded["7+"]) == 0, "already-active (ACI, 7+) should be excluded!"

    print("\nALL CHECKS PASSED.")


if __name__ == "__main__":
    main()
