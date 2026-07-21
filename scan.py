"""
Shared logic: scan config.TRADING_WATCHLIST (a fixed, explicit list) and
score every ticker with ONE composite /20 score (scoring.score_stock ->
technical /18, risk_manager.build_setup adds the SL/Target quality bonus
points -> /20). Called once daily by run_eod.py after market close.

v2 (this revision): the old version scored each ticker SEPARATELY per
horizon (7+/14+/30+, each with its own indicator periods) and returned
{horizon: [...]}. The new model has ONE score per stock and THREE
independent targets (T1/T2/T3) off a single entry — there's no horizon
split left to score against, "horizon" is now just a display label
(config.TARGET_HORIZON_LABEL) attached to each target inside
risk_manager.build_setup. scan_universe() therefore returns a flat list,
not a dict keyed by horizon.
"""
from config import MIN_BARS_REQUIRED, TRADING_WATCHLIST
from sheet_data_source import get_historical_data
from indicators import compute_all
from scoring import score_stock
from risk_manager import build_setup, rank_and_filter


def scan_universe(sheet) -> list:
    """
    Returns [{"ticker", "hist", "technical_score"}, ...] — one entry per
    ticker that had enough history and scored without error. `hist` (the
    raw OHLCV slice) is carried through for risk_manager's support/
    resistance lookup, so there's no second fetch needed there.
    """
    # De-duplicated, order preserved — a stock accidentally listed twice in
    # TRADING_WATCHLIST would otherwise get scored twice and could occupy
    # multiple ranking slots with itself, silently squeezing out a
    # genuinely different qualifier.
    watchlist = list(dict.fromkeys(TRADING_WATCHLIST))
    if len(watchlist) != len(TRADING_WATCHLIST):
        dupes = [t for t in set(TRADING_WATCHLIST) if TRADING_WATCHLIST.count(t) > 1]
        print(f"  [note] TRADING_WATCHLIST had duplicate(s), scanned once each: {dupes}")

    results = []
    for ticker in watchlist:
        try:
            hist = get_historical_data(sheet, ticker)
        except Exception as e:
            print(f"  [skip] {ticker}: {e}")
            continue
        if hist.empty:
            print(f"  [skip] {ticker}: no price data in RawDailyPrices yet")
            continue
        if len(hist) < max(MIN_BARS_REQUIRED, 2):
            print(f"  [skip] {ticker}: only {len(hist)} bar(s), needs >= {MIN_BARS_REQUIRED}")
            continue
        try:
            enriched = compute_all(hist)
            technical_score = score_stock(enriched)
            results.append({"ticker": ticker, "hist": hist, "technical_score": technical_score})
        except Exception as e:
            print(f"  [skip] {ticker}: {e}")
            continue
    return results


def build_setups(scan_results: list, exclude: set = None) -> list:
    """
    Turns each scanned ticker into a full setup (entry/SL/T1/T2/T3 + final
    /20 score) via risk_manager.build_setup. `exclude` is a set of tickers
    to skip before building setups (already-ACTIVE positions), so a
    currently-held stock doesn't both sit in Hold AND get re-added as a
    fresh Buy, and a lower-ranked-but-still-qualifying stock can take its
    slot instead of the list just shrinking. Not yet ranked/filtered —
    caller decides whether it wants the full list (e.g. for stats/logging)
    or the top N (via risk_manager.rank_and_filter).
    """
    exclude = exclude or set()
    return [
        build_setup(s["ticker"], s["hist"], s["technical_score"])
        for s in scan_results
        if s["ticker"] not in exclude
    ]


def build_watchlist(scan_results: list, top_n: int, exclude: set = None) -> list:
    """Convenience wrapper: build_setups() + rank_and_filter() in one call."""
    return rank_and_filter(build_setups(scan_results, exclude=exclude), top_n)
