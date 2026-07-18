"""
Single daily run — after market close.
Ingests today's pasted price data (RawStaging -> RawDailyPrices) -> scores
config.TRADING_WATCHLIST (a fixed, explicit list, not the whole A/B
universe) SEPARATELY per horizon (7+/14+/30+ each use their own indicator
periods AND RSI range, config.INDICATOR_PARAMS / config.RSI_RANGES) ->
builds each horizon's top-N list (config.TOP_N_EOD) from score >= MIN_SCORE
(9 or 10 out of 10), entry/SL/targets from support/resistance where found
(fallback percentages otherwise, see risk_manager.py), excluding tickers
already an open ACTIVE position for that horizon -> evaluates yesterday's
ACTIVE trades against today's close for Hold/Sell -> appends today's fresh
Buy list.

Investment (long-term SIP) watchlist checks run as a SEPARATE script
(scripts/investment_check.py), as an additional GitHub Actions step right
after this one, not from inside this file — see that script's docstring.
"""
from datetime import date
from config import TOP_N_EOD, HORIZONS, MIN_BARS_REQUIRED, MIN_SCORE
from market_calendar import is_market_holiday
from scan import scan_universe, build_watchlists
from sheet_data_source import ingest_staging, ingest_local_backfill, ledger_diagnostics
from sheets_manager import open_sheet, overwrite_tab
from state_manager import (
    evaluate_active_trades, apply_status_updates, add_new_buys,
    get_active_ticker_horizons, ACTIVE_HEADER, VIEW_HEADER,
)


def main():
    run_date = date.today().isoformat()
    if is_market_holiday(run_date):
        print(f"[{run_date}] DSE holiday — EOD run skipped.")
        return

    sheet = open_sheet()

    # -1. One-time historical backfill, if data/amarstock_backfill.csv has
    #     been committed to the repo (see README "Backfilling"). Always
    #     logged, even when not found.
    backfill_result = ingest_local_backfill(sheet)
    print(f"[{run_date}] Local backfill file: {backfill_result}")

    # 0. Pull in today's pasted prices (no-op if RawStaging is empty).
    ingest_result = ingest_staging(sheet, run_date)
    print(f"[{run_date}] Price ingest: {ingest_result}")

    diag = ledger_diagnostics(sheet)
    print(f"[{run_date}] RawDailyPrices ledger: {diag}")

    # 1. Evaluate existing ACTIVE trades against today's close -> Hold / Sell
    hold_rows, sell_rows, status_updates = evaluate_active_trades(sheet)
    apply_status_updates(sheet, status_updates)
    overwrite_tab(sheet, "hold", VIEW_HEADER, hold_rows)
    overwrite_tab(sheet, "sell", VIEW_HEADER, sell_rows)

    # Read AFTER apply_status_updates, so a stock that just closed today
    # (hit target/SL) is no longer considered "active" and is free to be
    # picked again if it still qualifies — only genuinely still-open
    # positions get excluded from today's fresh picks.
    active_pairs = get_active_ticker_horizons(sheet)
    print(f"[{run_date}] {len(active_pairs)} (ticker, horizon) position(s) "
          f"already ACTIVE — excluded from today's new picks.")

    # 2. Scan config.TRADING_WATCHLIST — scored independently per horizon
    print(f"[{run_date}] Scanning TRADING_WATCHLIST...")
    scan_results = scan_universe(sheet)
    for horizon in HORIZONS:
        h_scored = scan_results[horizon]
        if h_scored:
            qualifying = sum(1 for s in h_scored if s["score"] >= MIN_SCORE)
            best = max(s["score"] for s in h_scored)
            print(f"  {horizon}: {len(h_scored)} ticker(s) had enough history "
                  f"(>= {MIN_BARS_REQUIRED[horizon]} bars), {qualifying} scored "
                  f">= {MIN_SCORE}/10, best seen = {best}/10.")
        else:
            print(f"  {horizon}: 0 tickers had enough history yet "
                  f"(needs >= {MIN_BARS_REQUIRED[horizon]} bars).")

    watchlists = build_watchlists(scan_results, top_n=TOP_N_EOD, exclude=active_pairs)

    buy_rows = []
    for horizon in HORIZONS:
        setups = watchlists[horizon]
        add_new_buys(sheet, setups, run_date)
        buy_rows += [[
            s["ticker"], s["horizon"], s["entry_low"], s["entry_high"],
            s["stop_loss"], s["target_1"], s["target_2"], s["rrr"], s["score"],
            s["sl_source"], s["target_source"], run_date, "ACTIVE",
        ] for s in setups]
        for s in setups:
            print(f"  {horizon}: {s['ticker']} — score {s['score']}/10, "
                  f"SL via {s['sl_source']}, targets via {s['target_source']}, "
                  f"RRR {s['rrr']}")
        print(f"  {horizon}: {len(setups)} new Buy pick(s) added "
              f"(top {TOP_N_EOD}, fewer if fewer cleared the bar).")

    overwrite_tab(sheet, "buy", ACTIVE_HEADER, buy_rows)
    print(f"[{run_date}] EOD run complete: {len(buy_rows)} buy rows, "
          f"{len(hold_rows)} holds, {len(sell_rows)} sells.")


if __name__ == "__main__":
    main()
