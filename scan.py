"""
Shared logic: scan config.TRADING_WATCHLIST (a fixed, explicit list) and
score every ticker with ONE composite score (scoring.score_stock ->
technical /23, risk_manager.build_setup adds the SL/Target quality bonus
points -> /25). Called once daily by run_eod.py after market close.

v3 CHANGE (this revision): scan_universe() now fetches config.INDEX_TICKER
(DSEX) ONCE per run — not once per stock, since it's the same reading for
every ticker that day — and passes whether it closed up or down into
scoring.score_stock() for every ticker (the new DSEX relative-strength
point). If DSEX data isn't available/ingested yet, that point just
defaults to 0 for every stock today rather than failing the whole scan.
"""
from config import MIN_BARS_REQUIRED, TRADING_WATCHLIST, INDEX_TICKER
from sheet_data_source import get_historical_data
from indicators import compute_all
from scoring import score_stock
from risk_manager import build_setup, rank_and_filter


def _get_index_direction(sheet):
    """
    Returns True if DSEX closed up today vs yesterday, False if down/flat,
    or None if there isn't enough DSEX history yet / the fetch failed —
    callers treat None as "the DSEX point defaults to 0 today", not as an
    error that should stop the whole scan.
    """
    try:
        index_hist = get_historical_data(sheet, INDEX_TICKER)
    except Exception as e:
        print(f"  [note] {INDEX_TICKER} fetch failed ({e}) — DSEX relative-strength "
              f"point defaults to 0 for every stock today.")
        return None
    if index_hist is None or len(index_hist) < 2:
        print(f"  [note] {INDEX_TICKER}: not enough history yet for the DSEX "
              f"relative-strength point — it will default to 0 for every stock today.")
        return None
    index_change = float(index_hist["close"].iloc[-1]) - float(index_hist["close"].iloc[-2])
    return index_change > 0


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

    index_positive = _get_index_direction(sheet)
    print(f"  [note] {INDEX_TICKER} direction today: "
          f"{'UP' if index_positive else ('DOWN/FLAT' if index_positive is False else 'UNKNOWN')}")

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
            technical_score = score_stock(enriched, index_positive=index_positive)
            results.append({"ticker": ticker, "hist": hist, "technical_score": technical_score})
        except Exception as e:
            print(f"  [skip] {ticker}: {e}")
            continue
    return results


def build_setups(scan_results: list, exclude: set = None) -> list:
    """
    Turns each scanned ticker into a full setup (entry/SL/T1/T2/T3 + final
    /25 score) via risk_manager.build_setup. `exclude` is a set of tickers
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
