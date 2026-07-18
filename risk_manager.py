"""
Converts a raw score + price history into tradeable numbers: entry range,
stop-loss, targets, and RRR, for a given holding horizon.

Stop Loss and Targets are primarily SUPPORT/RESISTANCE based now, not pure
ATR multiples:
  - Stop Loss: the nearest confirmed swing-low support below entry within
    that horizon's sr_lookback_days (config.HORIZONS), minus a small
    buffer (config.SUPPORT_BUFFER_PCT). Falls back to sl_atr * ATR14 below
    entry if no support is found in that window.
  - Target 1 / Target 2: the nearest TWO confirmed swing-high resistance
    levels above entry in the same window. If only one is found, it's
    used for Target 1 and Target 2 falls back to a standard percentage
    above the entry HIGH price (fallback_pct_high). If none are found
    (typically a breakout to a new high, nothing above to reference),
    BOTH targets fall back to fallback_pct_low / fallback_pct_high above
    entry high.
See config.py's HORIZONS comment for the exact per-horizon numbers.
"""
from indicators import nearest_support, resistance_levels
from config import (
    HORIZONS, ENTRY_BAND_PCT, MIN_RRR, MIN_SCORE, SWING_WINDOW, SUPPORT_BUFFER_PCT,
)

RRR_TARGET = "target_2"  # which target the RRR viability check is measured against


def build_setup(ticker: str, hist, atr14: float, score: float, horizon: str) -> dict:
    """
    hist: the ticker's OHLCV history (needs close/high/low columns) used
    for support/resistance lookup — the SAME window sheet_data_source.
    get_historical_data() already returns, no separate fetch needed.
    """
    p = HORIZONS[horizon]
    close = float(hist["close"].iloc[-1])
    entry_low = round(close * (1 - ENTRY_BAND_PCT), 2)
    entry_high = round(close * (1 + ENTRY_BAND_PCT), 2)
    entry_mid = round(close, 2)

    lookback = p["sr_lookback_days"]

    support = nearest_support(hist, close, lookback, window=SWING_WINDOW, buffer_pct=SUPPORT_BUFFER_PCT)
    sl_source = "support"
    if support is None:
        sl = round(close - p["sl_atr"] * atr14, 2)
        sl_source = "atr_fallback"
    else:
        sl = round(support, 2)

    resistances = resistance_levels(hist, close, lookback, window=SWING_WINDOW)
    fallback_t1 = entry_high * (1 + p["fallback_pct_low"])
    fallback_t2 = entry_high * (1 + p["fallback_pct_high"])

    if len(resistances) >= 2:
        # resistance_levels() returns them sorted ascending (nearest first),
        # so t1 < t2 is guaranteed here.
        t1, t2 = resistances[0], resistances[1]
        target_source = "resistance"
    elif len(resistances) == 1:
        r = resistances[0]
        if r <= fallback_t2:
            # the found level sits within/below the fallback ceiling -> use
            # it as the closer T1, fallback ceiling as a T2 stretch goal.
            t1, t2 = r, fallback_t2
            target_source = "resistance_plus_fallback"
        else:
            # the found level is BEYOND the fallback ceiling — using it as
            # T1 would make T1 > T2 (a real bug this test caught: a
            # genuinely good, structure-grounded resistance was getting
            # silently discarded because of ordering, not because
            # anything was wrong with it). Use the conservative fallback
            # floor as the near target, the real resistance as a farther
            # stretch T2 instead.
            t1, t2 = fallback_t1, r
            target_source = "fallback_plus_resistance"
    else:
        t1, t2 = fallback_t1, fallback_t2
        target_source = "fallback_pct"

    if t1 > t2:  # defensive — shouldn't trigger given the above, but never ship a broken ordering
        t1, t2 = t2, t1
    t1, t2 = round(t1, 2), round(t2, 2)

    risk = entry_mid - sl
    reward_t1 = t1 - entry_mid
    reward_t2 = t2 - entry_mid
    reward = reward_t2 if RRR_TARGET == "target_2" else reward_t1
    rrr = round(reward / risk, 2) if risk > 0 else 0

    setup = {
        "ticker": ticker,
        "horizon": horizon,
        "score": score,
        "close": close,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "stop_loss": sl,
        "target_1": t1,
        "target_2": t2,
        "rrr": rrr,
        "sl_source": sl_source,
        "target_source": target_source,
    }
    setup["valid"] = risk > 0 and t2 > t1 > entry_mid and rrr >= MIN_RRR and score >= MIN_SCORE
    return setup


def rank_and_filter(setups: list, top_n: int) -> list:
    """Keep only valid setups, sort by score (then RRR) desc, slice to top_n."""
    valid = [s for s in setups if s["valid"]]
    valid.sort(key=lambda s: (s["score"], s["rrr"]), reverse=True)
    return valid[:top_n]
