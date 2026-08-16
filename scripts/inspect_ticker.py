"""
CLI tool to peek at a ticker's CURRENT state under the combined
regime-switching weekly model (Branch A: Sideways/Downtrend dip-buy,
Branch B: Uptrend breakout) -- replaces the old v2 daily composite-score
inspector, which inspected a retired model (indicators.compute_all /
scoring.score_stock / risk_manager.build_setup no longer exist in the
weekly pipeline).

Shows: today's regime (which branch is live), the ticker's raw feature
values for BOTH branches (so you can see how close it is even when the
regime doesn't currently favor its branch), and a plain pass/fail per
screening rule.

Usage: python scripts/inspect_ticker.py <TICKER>
"""
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import weekly_config as wc
import weekly_engine as we
from sheets_manager import open_sheet


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/inspect_ticker.py <TICKER>")
        sys.exit(1)

    ticker = sys.argv[1].upper()
    sheet = open_sheet()

    print(f"Loading ledger...")
    per_symbol, all_dates = we.load_ledger(sheet)
    if not all_dates:
        print("Error: no price history in RawDailyPrices yet.")
        return
    if ticker not in per_symbol:
        print(f"Error: no data found for {ticker} in RawDailyPrices.")
        return
    if wc.INDEX_SYMBOL not in per_symbol:
        print(f"Error: index series {wc.INDEX_SYMBOL} missing from RawDailyPrices.")
        return

    date_pos = {d: i for i, d in enumerate(all_dates)}
    latest_date = all_dates[-1]
    if date_pos.get(latest_date, 0) < wc.MIN_BARS_REQUIRED:
        print(f"Warning: only {date_pos[latest_date] + 1} bars in the whole ledger so far "
              f"(need >= {wc.MIN_BARS_REQUIRED}) -- readings below may not be screen-eligible yet.")

    is_uptrend = we._is_uptrend_series(per_symbol)
    up_today = bool(is_uptrend.get(latest_date, False))
    live_branch = "B (Uptrend breakout)" if up_today else "A (Sideways/Downtrend dip-buy)"

    print(f"\n--- {ticker} as of {latest_date} ---")
    print(f"Today's regime: {'UPTREND' if up_today else 'NOT-UPTREND'}  ->  live branch: {live_branch}")

    # ---- Branch A readout ----
    feats_a, idx_ret20 = we._build_features_a(per_symbol)
    print("\n[Branch A -- dip-buy screen]")
    if ticker not in feats_a or latest_date not in feats_a[ticker].index:
        print("  Not enough history yet for Branch A features.")
    else:
        row = feats_a[ticker].loc[latest_date]
        idx_r = idx_ret20.loc[latest_date] if latest_date in idx_ret20.index and pd.notna(idx_ret20.loc[latest_date]) else None
        rel = (row["ret20"] - idx_r) if idx_r is not None and pd.notna(row["ret20"]) else None
        prox_pct = ((row["close"] - row["roll_low60"]) / row["roll_low60"] * 100) if pd.notna(row["roll_low60"]) else None

        def flag(ok):
            return "PASS" if ok else "fail"

        print(f"  RSI({wc.RSI_PERIOD}):            {row['rsi']:.2f}   "
              f"[{flag(wc.RSI_MIN < row['rsi'] < wc.RSI_MAX)}]  need {wc.RSI_MIN} < RSI < {wc.RSI_MAX}")
        print(f"  Proximity to 60d low:  {prox_pct:.2f}%  "
              f"[{flag(prox_pct is not None and prox_pct <= wc.PROXIMITY_TO_LOW_MAX_PCT)}]  need <= {wc.PROXIMITY_TO_LOW_MAX_PCT}%"
              if prox_pct is not None else "  Proximity to 60d low:  n/a")
        print(f"  20d turnover:          {row['turnover20']:,.0f}  "
              f"[{flag(row['turnover20'] >= wc.MIN_TURNOVER_20D)}]  need >= {wc.MIN_TURNOVER_20D:,.0f}")
        print(f"  20d volatility:        {row['vol20']:.2f}%  "
              f"[{flag(row['vol20'] >= wc.MIN_VOL20_PCT)}]  need >= {wc.MIN_VOL20_PCT}%")
        if rel is not None:
            print(f"  RelStrength20 vs DSEX: {rel:.4f}  "
                  f"[{flag(rel < wc.RS_ELIGIBILITY_MAX)}]  need < {wc.RS_ELIGIBILITY_MAX} (rank metric -- most negative wins)")
        else:
            print(f"  RelStrength20 vs DSEX: n/a")
        print(f"  Regime gate:           [{flag(not up_today)}]  Branch A only fires NOT-UPTREND weeks")

    # ---- Branch B readout ----
    feats_b = we._build_features_b(per_symbol)
    print("\n[Branch B -- uptrend breakout screen]")
    if ticker not in feats_b or latest_date not in feats_b[ticker].index:
        print("  Not enough history yet for Branch B features.")
    else:
        row = feats_b[ticker].loc[latest_date]

        def flag(ok):
            return "PASS" if ok else "fail"

        rsi_ok = wc.B_RSI_LO <= row["rsi"] <= wc.B_RSI_HI and row["rsi_prev"] < wc.B_RSI_LO
        vol_ok = pd.notna(row["vol20_frac"]) and row["vol20_frac"] >= wc.B_MIN_VOL20_FRAC
        volratio_ok = pd.notna(row["vol_ratio"]) and row["vol_ratio"] >= wc.B_VOL_MULT
        candle_ok = row["close"] > row["open"] and row["volume"] > row["volume_prev"]

        print(f"  RSI({wc.B_RSI_PERIOD}):            {row['rsi']:.2f} (prev {row['rsi_prev']:.2f})  "
              f"[{flag(rsi_ok)}]  need {wc.B_RSI_LO} <= RSI <= {wc.B_RSI_HI} and prev RSI < {wc.B_RSI_LO} (fresh cross)")
        print(f"  20d volatility (frac): {row['vol20_frac']:.4f}  "
              f"[{flag(vol_ok)}]  need >= {wc.B_MIN_VOL20_FRAC}"
              if pd.notna(row["vol20_frac"]) else "  20d volatility (frac): n/a")
        print(f"  Volume / EMA20 ratio:  {row['vol_ratio']:.2f}x  "
              f"[{flag(volratio_ok)}]  need >= {wc.B_VOL_MULT}x (rank metric -- highest wins)"
              if pd.notna(row["vol_ratio"]) else "  Volume / EMA20 ratio:  n/a")
        print(f"  Green candle + rising vol: close {row['close']:.2f} vs open {row['open']:.2f}, "
              f"vol {row['volume']:,.0f} vs prev {row['volume_prev']:,.0f}  [{flag(candle_ok)}]")
        print(f"  Regime gate:           [{flag(up_today)}]  Branch B only fires UPTREND weeks")


if __name__ == "__main__":
    main()
