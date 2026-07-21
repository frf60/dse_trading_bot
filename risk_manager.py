"""
Converts a technical score + price history into ONE tradeable setup: ONE
entry band, ONE stop-loss, and THREE independent targets (T1/T2/T3) off
the same entry.

v3 (this revision, per your explicit answers):
  - Targets are PURE RRR multiples off entry_high (T1=1.0R, T2=1.5R,
    T3=2.0R -- config.TARGET_RRR). "R" (risk-per-share) = entry_high - stop_loss.
    No more horizon-specific % bands, no more resistance-based target
    placement -- resistance only feeds the target_quality bonus point below.
  - Stop loss: nearest confirmed swing-low support below price, if one
    exists within SR_LOOKBACK_DAYS. Otherwise flat SL_FALLBACK_PCT (6%)
    below entry_high (your answer: "Fixed % (entry_high er 6% niche)").
  - T1/T2/T3 are tracked INDEPENDENTLY once the trade is live -- see
    state_manager.py below. Hitting T1 does NOT close T2/T3; they keep
    running against the SAME stop-loss until each is separately hit, or
    the stop is hit (which closes all still-open targets at once).
  - The 2 points scoring.py's technical_total (max 18) doesn't cover are
    computed HERE, because they need the support/resistance lookup:
      sl_quality      (1 pt if SL sits on real support, 0 if flat-% fallback)
      target_quality  (1 pt if a real resistance level sits at/near any of
                        T1/T2/T3 -- informational only, does NOT move the
                        target, only confirms it)
    final score = technical_total + sl_quality + target_quality, checked
    against MIN_SCORE (out of SCORE_MAX = 20).
"""
from indicators import nearest_support, resistance_levels
from config import (
    ENTRY_BAND_PCT, SWING_WINDOW, SR_LOOKBACK_DAYS, SUPPORT_BUFFER_PCT,
    SL_FALLBACK_PCT, MIN_TARGET_BUFFER_PCT, TARGET_RRR, TARGET_HORIZON_LABEL,
    SCORE_MAX, MIN_SCORE,
    SL_SUPPORT_POINT, SL_FALLBACK_POINT,
    TARGET_RESISTANCE_POINT, TARGET_FALLBACK_POINT,
)

TARGET_KEYS = ("target_1", "target_2", "target_3")


def build_setup(ticker: str, hist, technical_score: dict) -> dict:
    """
    hist: ticker's OHLCV history (needs high/low/close cols) -- the SAME
    window sheet_data_source.get_historical_data() already returns.
    technical_score: output of scoring.score_stock(indicators.compute_all(hist))
      -- {"technical_total": int (0-18), "technical_max": 18, "breakdown": {...}}
    """
    close = float(hist["close"].iloc[-1])
    entry_low = round(close * (1 - ENTRY_BAND_PCT), 2)
    entry_high = round(close * (1 + ENTRY_BAND_PCT), 2)
    entry_mid = round(close, 2)

    # ==========================================
    # 1. STOP LOSS FIRST (targets are calculated off entry_high AND risk,
    #    and risk needs the stop-loss, so SL has to be settled before T1-T3)
    # ==========================================
    support = nearest_support(hist, close, SR_LOOKBACK_DAYS,
                               window=SWING_WINDOW, buffer_pct=SUPPORT_BUFFER_PCT)
    fallback_sl = round(entry_high * (1 - SL_FALLBACK_PCT), 2)

    if support is not None and support < entry_high:
        sl = round(support, 2)
        sl_source = "support"
        sl_quality = SL_SUPPORT_POINT
    else:
        sl = fallback_sl
        sl_source = "fallback_pct"
        sl_quality = SL_FALLBACK_POINT

    risk_per_share = round(entry_high - sl, 2)   # "R" -- the RRR unit

    # ==========================================
    # 2. TARGETS -- pure RRR multiples off entry_high, each tracked
    #    independently once live (state_manager.py)
    # ==========================================
    targets = {key: round(entry_high + risk_per_share * TARGET_RRR[key], 2)
               for key in TARGET_KEYS}

    # Informational only: does a real resistance level confirm any target?
    # This does NOT move the target -- it only decides the target_quality
    # bonus point (your rule: "target jodi proper resistance e thake tahole 1").
    resistances = resistance_levels(hist, close, SR_LOOKBACK_DAYS, window=SWING_WINDOW)
    target_quality = TARGET_FALLBACK_POINT
    target_source = "rrr"
    for r in resistances:
        if any(abs(r - t) / t <= MIN_TARGET_BUFFER_PCT for t in targets.values()):
            target_quality = TARGET_RESISTANCE_POINT
            target_source = "rrr_confirmed_by_resistance"
            break

    # ==========================================
    # 3. FINAL SCORE /20 = technical_total (18, from scoring.py) + 2 bonus pts
    # ==========================================
    technical_total = technical_score["technical_total"]
    final_score = technical_total + sl_quality + target_quality

    setup = {
        "ticker": ticker,
        "score": final_score,
        "technical_total": technical_total,
        "sl_quality": sl_quality,
        "target_quality": target_quality,
        "close": close,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "stop_loss": sl,
        "sl_source": sl_source,
        "risk_per_share": risk_per_share,
        "target_source": target_source,
    }
    for key in TARGET_KEYS:
        setup[key] = targets[key]
        setup[f"{key}_rrr"] = TARGET_RRR[key]
        setup[f"{key}_horizon_label"] = TARGET_HORIZON_LABEL[key]

    setup["valid"] = (
        risk_per_share > 0
        and targets["target_1"] < targets["target_2"] < targets["target_3"]
        and targets["target_1"] > entry_mid
        and MIN_SCORE <= final_score <= SCORE_MAX
    )
    return setup


def rank_and_filter(setups: list, top_n: int) -> list:
    """
    Keep only valid setups, sort by score desc (tiebreak: smaller
    risk_per_share first -- a tighter stop is preferred when scores tie),
    slice to top_n. Runs across the WHOLE trading list at once -- there's
    no per-horizon split anymore, horizon is just a display label now.
    """
    valid = [s for s in setups if s["valid"]]
    valid.sort(key=lambda s: (s["score"], -s["risk_per_share"]), reverse=True)
    return valid[:top_n]
