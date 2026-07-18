"""
Shared logic: scan config.TRADING_WATCHLIST (a fixed, explicit list — not
the whole A/B category universe anymore, per your explicit request) and
score every ticker SEPARATELY for each horizon (7+/14+/30+ each use their
own indicator periods AND RSI range — see config.INDICATOR_PARAMS /
config.RSI_RANGES), then turn scores into watchlists using support/
resistance-based (or fallback %) entry/SL/targets. Called once daily by
run_eod.py after market close.
"""
from config import MIN_BARS_REQUIRED, HORIZONS, INDICATOR_PARAMS, TOP_N_EOD, TRADING_WATCHLIST
from sheet_data_source import get_historical_data
from indicators import compute_all
from scoring import score_row
from risk_manager import build_setup, rank_and_filter


def scan_universe(sheet) -> dict:
    """
    Returns {horizon: [{"ticker","hist","atr14","score"}, ...]}. The same
    ticker can appear with a different score under each horizon key, since
    each horizon computes its own indicators from its own periods (and its
    own RSI range) — that's the point, not a bug, if 7+/14+/30+ scores
    differ for the same stock. `hist` (the raw OHLCV slice) is carried
    through for risk_manager's support/resistance lookup — no separate
    fetch needed there.
    """
    results = {h: [] for h in HORIZONS}
    for ticker in TRADING_WATCHLIST:
        try:
            hist = get_historical_data(sheet, ticker)
        except Exception as e:
            print(f"  [skip] {ticker}: {e}")
            continue
        if hist.empty:
            print(f"  [skip] {ticker}: no price data in RawDailyPrices yet")
            continue

        for horizon in HORIZONS:
            if len(hist) < max(MIN_BARS_REQUIRED[horizon], 2):
                continue  # not enough history for this horizon's periods yet
            try:
                enriched = compute_all(hist, INDICATOR_PARAMS[horizon])
                curr, prev = enriched.iloc[-1], enriched.iloc[-2]
                result = score_row(curr, prev, horizon)
                results[horizon].append({
                    "ticker": ticker,
                    "hist": hist,
                    "atr14": float(curr["atr14"]),
                    "score": result["total"],
                })
            except Exception as e:
                print(f"  [skip] {ticker} ({horizon}): {e}")
                continue
    return results


def build_watchlists(scan_results: dict, top_n: int = TOP_N_EOD, exclude: set = None) -> dict:
    """
    {horizon: [setup, ...]} — each setup already score/RRR-filtered and
    ranked. `exclude` is a set of (ticker, horizon) pairs to skip entirely
    before ranking (already-ACTIVE positions), so a currently-held stock
    doesn't both sit in Hold AND get re-added as a fresh Buy, and so a
    lower-ranked-but-still-qualifying stock can take its place in the top_n
    instead of just shrinking the list.
    """
    exclude = exclude or set()
    watchlists = {}
    for horizon in HORIZONS:
        setups = [
            build_setup(s["ticker"], s["hist"], s["atr14"], s["score"], horizon)
            for s in scan_results[horizon]
            if (s["ticker"], horizon) not in exclude
        ]
        watchlists[horizon] = rank_and_filter(setups, top_n)
    return watchlists

