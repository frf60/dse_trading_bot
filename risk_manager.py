"""
Converts a raw score + ATR into tradeable numbers: entry range, stop-loss,
targets, and RRR, for a given holding horizon. 

Both SL and Targets scale with each stock's own ATR, holding a FIXED
risk:reward ratio (t2_atr/sl_atr) per horizon — 1:3 / 1:5 / 1:8 for
7+/14+/30+ — a deliberate choice made after weighing the tradeoff: this
makes MIN_RRR effectively a no-op (see config.py's HORIZONS comment for
the full reasoning and the earlier flat-percentage-target design this
replaced).
"""
from config import HORIZONS, ENTRY_BAND_PCT, MIN_RRR, MIN_SCORE

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
    setup["valid"] = risk > 0 and rrr >= MIN_RRR and score >= MIN_SCORE
    return setup


def rank_and_filter(setups: list, top_n: int) -> list:
    """Keep only RRR-valid setups, sort by score (then RRR) desc, slice to top_n."""
    valid = [s for s in setups if s["valid"]]
    valid.sort(key=lambda s: (s["score"], s["rrr"]), reverse=True)
    return valid[:top_n]
