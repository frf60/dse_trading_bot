"""
3:00 PM run — after market close.
Ingests today's pasted price data (RawStaging -> RawDailyPrices) -> full
universe scan -> score everything -> build 7+/14+/30+ watchlists (up to 5
each = up to 15 Buy rows, fewer if a stock ranks in more than one horizon)
-> evaluate yesterday's ACTIVE trades against today's close for Hold/Sell
-> append tomorrow's Buy list.
"""
from datetime import date
from config import TOP_N_EOD, HORIZONS
from market_calendar import is_market_holiday
from scan import scan_universe, build_watchlists
from sheet_data_source import ingest_staging, ingest_local_backfill, ledger_diagnostics
from sheets_manager import open_sheet, overwrite_tab
from state_manager import (
    evaluate_active_trades, apply_status_updates, add_new_buys,
    ACTIVE_HEADER, VIEW_HEADER,
)


def main():
    run_date = date.today().isoformat()
    if is_market_holiday(run_date):
        print(f"[{run_date}] DSE holiday — EOD run skipped.")
        return

    sheet = open_sheet()

    # -1. One-time historical backfill, if data/amarstock_backfill.csv has
    #     been committed to the repo (see README "Backfilling"). Always
    #     logged, even when not found — this used to be silent, which is
    #     exactly why "still 0 tickers scored" was hard to diagnose.
    backfill_result = ingest_local_backfill(sheet)
    print(f"[{run_date}] Local backfill file: {backfill_result}")

    # 0. Pull in today's pasted prices (no-op if RawStaging is empty — e.g.
    #    if you paste after this run already fired, see README "Timing").
    ingest_result = ingest_staging(sheet, run_date)
    print(f"[{run_date}] Price ingest: {ingest_result}")

    # Ground truth on what's actually in the ledger now, so "0 tickers
    # scored" (if it happens) comes with an immediate explanation instead
    # of a guessing game.
    diag = ledger_diagnostics(sheet)
    print(f"[{run_date}] RawDailyPrices ledger: {diag}")

    # 1. Evaluate existing ACTIVE trades against today's close -> Hold / Sell
    hold_rows, sell_rows, status_updates = evaluate_active_trades(sheet)
    apply_status_updates(sheet, status_updates)
    overwrite_tab(sheet, "hold", VIEW_HEADER, hold_rows)
    overwrite_tab(sheet, "sell", VIEW_HEADER, sell_rows)

    # 2. Scan the full A/B universe and build tomorrow's watchlists
    print(f"[{run_date}] Scanning universe...")
    scored = scan_universe(sheet)
    print(f"[{run_date}] {len(scored)} tickers scored.")
    if scored:
        above_7 = sum(1 for s in scored if s["score"] >= 7)
        best = max(s["score"] for s in scored)
        print(f"[{run_date}] Score distribution: {above_7}/{len(scored)} scored >= 7 "
              f"(MIN_SCORE gate), best score seen = {best}/10. An empty Buy list for a "
              f"horizon below just means none of those cleared MIN_SCORE and MIN_RRR "
              f"together for that horizon — not an error.")
    watchlists = build_watchlists(scored, top_n=TOP_N_EOD)

    buy_rows = []
    for horizon in HORIZONS:
        setups = watchlists[horizon]
        add_new_buys(sheet, setups, run_date)
        buy_rows += [[
            s["ticker"], s["horizon"], s["entry_low"], s["entry_high"],
            s["stop_loss"], s["target_1"], s["target_2"], s["rrr"], s["score"],
            run_date, "ACTIVE",
        ] for s in setups]

    overwrite_tab(sheet, "buy", ACTIVE_HEADER, buy_rows)
    print(f"[{run_date}] EOD run complete: {len(buy_rows)} buy rows, "
          f"{len(hold_rows)} holds, {len(sell_rows)} sells.")


if __name__ == "__main__":
    main()
