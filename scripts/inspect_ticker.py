"""
Diagnostic: prints the EXACT indicator values this system computed for a
given ticker on the latest available day, for each horizon — so you can
compare directly against a chart/platform showing different numbers.

Why numbers might legitimately differ from a chart you're looking at:
each horizon uses its OWN indicator periods (config.INDICATOR_PARAMS) —
30+ uses RSI(21) and MACD(19,39,9), not the RSI(14)/MACD(12,26,9) most
charting tools default to. A slower RSI/MACD can show a meaningfully
different (and legitimately more or less bullish) reading than a
standard-period chart for the same stock on the same day — that's the
point of using different periods per horizon, not a bug. This script
exists so you can check whether that's actually what's happening, rather
than taking it on faith.

Run: python scripts/inspect_ticker.py TICKER [HORIZON]
  TICKER: e.g. WALTONHIL
  HORIZON: 7+, 14+, or 30+ (omit to print all three)
Needs GOOGLE_SERVICE_ACCOUNT_JSON, same as the rest of the project.
"""
import sys
import config
from sheets_manager import open_sheet
from sheet_data_source import get_historical_data
from indicators import compute_all
from scoring import score_row
from risk_manager import build_setup


def inspect(ticker: str, horizons=None):
    horizons = horizons or list(config.HORIZONS.keys())
    sheet = open_sheet()
    hist = get_historical_data(sheet, ticker, days=config.HISTORY_DAYS)
    if hist.empty:
        print(f"No data for {ticker} in RawDailyPrices — check the exact ticker spelling.")
        return

    print(f"{ticker}: {len(hist)} day(s) of history in RawDailyPrices, "
          f"latest close = {hist['close'].iloc[-1]}")
    print()

    for horizon in horizons:
        params = config.INDICATOR_PARAMS[horizon]
        min_bars = config.MIN_BARS_REQUIRED[horizon]
        if len(hist) < max(min_bars, 2):
            print(f"[{horizon}] not enough history yet "
                  f"(needs >= {min_bars} bars, have {len(hist)}) — skipped.\n")
            continue

        enriched = compute_all(hist, params)
        curr, prev = enriched.iloc[-1], enriched.iloc[-2]
        result = score_row(curr, prev, horizon)
        setup = build_setup(ticker, hist, float(curr["atr14"]), result["total"], horizon)

        print(f"=== {horizon} — RSI({params['rsi']}), "
              f"MACD({params['macd_fast']},{params['macd_slow']},{params['macd_signal']}), "
              f"healthy RSI range {config.RSI_RANGES[horizon]} ===")
        print(f"  RSI({params['rsi']})        = {curr['rsi']:.2f}")
        print(f"  MACD line / signal / hist = {curr['macd_line']:.3f} / "
              f"{curr['signal_line']:.3f} / {curr['macd_hist']:.3f} "
              f"(previous hist = {prev['macd_hist']:.3f})")
        print(f"  EMA{params['ema_fast']} / EMA{params['ema_slow']}     = "
              f"{curr['ema_fast']:.2f} / {curr['ema_slow']:.2f}")
        print(f"  Volume / {params['vol_avg']}-day avg = "
              f"{curr['volume']:.0f} / {curr['vol_avg']:.0f}")
        print(f"  OBV / {params['obv_ma']}-day avg OBV = "
              f"{curr['obv']:.0f} / {curr['obv_ma']:.0f}")
        print(f"  ATR14                     = {curr['atr14']:.2f}")
        print(f"  Score breakdown: {result['breakdown']}")
        print(f"  Total score: {result['total']}/10")
        print(f"  Setup: entry {setup['entry_low']}-{setup['entry_high']}, "
              f"SL {setup['stop_loss']} ({setup['sl_source']}), "
              f"T1 {setup['target_1']}, T2 {setup['target_2']} ({setup['target_source']}), "
              f"RRR {setup['rrr']}, valid={setup['valid']}")
        print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python scripts/inspect_ticker.py TICKER [HORIZON]")
    ticker = sys.argv[1].upper()
    horizons = [sys.argv[2]] if len(sys.argv) > 2 else None
    inspect(ticker, horizons)
