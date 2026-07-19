"""
Converts a raw score + price history into tradeable numbers: entry range,
stop-loss, targets, and RRR, for a given holding horizon.

Stop Loss and Targets are primarily SUPPORT/RESISTANCE based now:
  - Target 1 / Target 2: the nearest TWO confirmed swing-high resistance
    levels above entry. Must be at least 3% (MIN_TARGET_BUFFER_PCT) above entry_high.
    Falls back to horizon-specific percentages (e.g., 4-8%, 9-12%, 13-20%) if no
    resistance is found.
  - Stop Loss: looks for a support level strictly between 3% and 5%
    (MIN_SUPPORT_DROP_PCT to MAX_SUPPORT_DROP_PCT) below entry_low.
    If no support exists in that exact window, falls back to calculating SL
    based on a strict 1:2 Risk/Reward Ratio against Target 1.
"""
from indicators import nearest_support, resistance_levels
from config import (
    HORIZONS, ENTRY_BAND_PCT, MIN_RRR, MIN_SCORE, SWING_WINDOW, SUPPORT_BUFFER_PCT,
    MIN_TARGET_BUFFER_PCT, MIN_SUPPORT_DROP_PCT, MAX_SUPPORT_DROP_PCT
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

    # ==========================================
    # 1. CALCULATE TARGETS FIRST
    # (Stop Loss fallback now depends on Target 1)
    # ==========================================
    resistances = resistance_levels(hist, close, lookback, window=SWING_WINDOW)
    min_meaningful_target = entry_high * (1 + MIN_TARGET_BUFFER_PCT)
    
    # A resistance closer than MIN_TARGET_BUFFER_PCT (3%) to entry_high isn't usable.
    resistances = [r for r in resistances if r >= min_meaningful_target]

    fallback_t1 = entry_high * (1 + p["fallback_pct_low"])
    fallback_t2 = entry_high * (1 + p["fallback_pct_high"])

    if len(resistances) >= 2:
        # resistance_levels() returns them sorted ascending (nearest first)
        t1, t2 = resistances[0], resistances[1]
        target_source = "resistance"
    elif len(resistances) == 1:
        r = resistances[0]
        if r <= fallback_t2:
            # the found level sits within/below the fallback ceiling -> use it as T1
            t1, t2 = r, fallback_t2
            target_source = "resistance_plus_fallback"
        else:
            # the found level is BEYOND the fallback ceiling -> use fallback as T1, real resistance as T2 stretch
            t1, t2 = fallback_t1, r
            target_source = "fallback_plus_resistance"
    else:
        t1, t2 = fallback_t1, fallback_t2
        target_source = "fallback_pct"

    if t1 > t2:  # defensive ordering check
        t1, t2 = t2, t1
    t1, t2 = round(t1, 2), round(t2, 2)

    # ==========================================
    # 2. CALCULATE STOP LOSS
    # ==========================================
    support = nearest_support(hist, close, lookback, window=SWING_WINDOW, buffer_pct=SUPPORT_BUFFER_PCT)
    
    # Define the strict 3% to 5% valid drop window below entry_low
    upper_support_bound = entry_low * (1 - MIN_SUPPORT_DROP_PCT)
    lower_support_bound = entry_low * (1 - MAX_SUPPORT_DROP_PCT)

    if support is not None and (lower_support_bound <= support <= upper_support_bound):
        sl = round(support, 2)
        sl_source = "support"
    else:
        # FALLBACK: RRR 1:2 against Target 1
        # Risk = Reward / 2 -> SL = entry_mid - (Reward_T1 / 2)
        reward_t1_raw = t1 - entry_mid
        sl = round(entry_mid - (reward_t1_raw / 2), 2)
        sl_source = "rrr_1_2_fallback"

    # ==========================================
    # 3. CALCULATE RISK & REWARD
    # ==========================================
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
    setup["valid"] = (
        risk > 0
        and t2 > t1 > entry_mid
        and t1 >= min_meaningful_target  # guarantee even if a future code path forgets the upstream filter
        and rrr >= MIN_RRR
        and score >= MIN_SCORE
    )
    return setup


def rank_and_filter(setups: list, top_n: int) -> list:
    """Keep only valid setups, sort by score (then RRR) desc, slice to top_n."""
    valid = [s for s in setups if s["valid"]]
    valid.sort(key=lambda s: (s["score"], s["rrr"]), reverse=True)
    return valid[:top_n]
