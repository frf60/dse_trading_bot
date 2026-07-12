"""
Shared logic: scan the filtered A/B universe, score every ticker, and turn
scores into per-horizon watchlists. Called once daily by run_eod.py after
market close.

Data comes from RawDailyPrices (see sheet_data_source.py) rather than
scraping DSE directly — dsebd.org's own robots.txt disallows automated
access sitewide, so this project stopped treating it as a live source.
"""
from config import ALLOWED_CATEGORIES, EXCLUDED_SECTORS, MIN_BARS_REQUIRED, HORIZONS, TOP_N_EOD
from data_fetcher import get_ticker_universe  # category/sector CSV — a one-time human-compiled list, unaffected by the robots.txt issue
from sheet_data_source import get_historical_data
from indicators import compute_all
from scoring import score_row
from risk_manager import build_setup, rank_and_filter


def scan_universe(sheet) -> list:
    """Returns [{ticker, close, atr14, score}, ...] for every stock that passes filters."""
    universe = get_ticker_universe()
    universe = universe[
        universe["category"].isin(ALLOWED_CATEGORIES)
        & ~universe["sector"].isin(EXCLUDED_SECTORS)
    ]

    scored = []
    for ticker in universe["ticker"]:
        try:
            hist = get_historical_data(sheet, ticker)
            if len(hist) < max(MIN_BARS_REQUIRED, 2):  # scoring needs a prior row too
                continue
            enriched = compute_all(hist)
            curr, prev = enriched.iloc[-1], enriched.iloc[-2]
            result = score_row(curr, prev)
            scored.append({
                "ticker": ticker,
                "close": float(curr["close"]),
                "atr14": float(curr["atr14"]),
                "score": result["total"],
            })
        except Exception as e:
            print(f"  [skip] {ticker}: {e}")
            continue  # one bad/missing ticker shouldn't kill the whole run
    return scored


def build_watchlists(scored: list, top_n: int = TOP_N_EOD) -> dict:
    """{horizon: [setup, ...]} — each setup already RRR-filtered and ranked."""
    watchlists = {}
    for horizon in HORIZONS:
        setups = [
            build_setup(s["ticker"], s["close"], s["atr14"], s["score"], horizon)
            for s in scored
        ]
        watchlists[horizon] = rank_and_filter(setups, top_n)
    return watchlists
