"""
Converts a raw score + ATR into tradeable numbers: entry range, stop-loss,
targets, and RRR, for a given holding horizon. Rejects anything below MIN_RRR.

IMPORTANT FIX vs. the original blueprint:
The blueprint's own SL/T1 ATR multiples make RRR (measured against Target 1)
mathematically incapable of ever reaching 1.5:
    7+ :  T1_atr/SL_atr = 1.5/1.5 = 1.00
    14+:  T1_atr/SL_atr = 2.5/2.0 = 1.25
    30+:  T1_atr/SL_atr = 4.0/3.0 = 1.33
All three are below 1.5 regardless of the stock's actual ATR — so gating on
T1 would silently return zero qualifying stocks, every horizon, every day.
Target 2's multiples DO clear the bar (1.67 / 2.00 / 2.33), so the RRR
condition is evaluated against Target 2 here. T1 is still calculated and
shown as the closer, partial-profit level. Flip RRR_TARGET below if you'd
rather redefine the gate some other way.
"""
from config import HORIZONS, ENTRY_BAND_PCT, MIN_RRR

RRR_TARGET = "target_2"  # which target the RRR viability check is measured against


def build_setup(ticker: str, close: float, atr14: float, score: float, horizon: str) -> dict:
    p = HORIZONS[horizon]
    entry_low = round(close * (1 - ENTRY_BAND_PCT), 2)
    entry_high = round(close * (1 + ENTRY_BAND_PCT), 2)
    entry_mid = round(close, 2)

    sl = round(close - p["sl_atr"] * atr14, 2)
    t1 = round(close + p["t1_atr"] * atr14, 2)
    t2 = round(close + p["t2_atr"] * atr14, 2)

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
    }
    setup["valid"] = risk > 0 and rrr >= MIN_RRR
    return setup


def rank_and_filter(setups: list, top_n: int) -> list:
    """Keep only RRR-valid setups, sort by score (then RRR) desc, slice to top_n."""
    valid = [s for s in setups if s["valid"]]
    valid.sort(key=lambda s: (s["score"], s["rrr"]), reverse=True)
    return valid[:top_n]
