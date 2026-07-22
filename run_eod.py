"""
Single daily run — after market close.
Ingests today's pasted price data (RawStaging -> RawDailyPrices) -> scores
config.TRADING_WATCHLIST (a fixed, explicit list) with ONE composite /25
score per stock (RSI 9 + MACD 3 + Volume 3 + MA 3 + DSEX relative-strength
1 + Low-proximity 4 + SL-quality 1 + Target-quality 1 — see scoring.py /
risk_manager.py) -> builds today's top-N list (config.TOP_N_DAILY) from
stocks scoring >= MIN_SCORE, each with ONE entry, ONE stop-loss
(support-based or the flat 6% fallback), and THREE independent RRR
targets (T1 1.0R / T2 1.5R / T3 2.0R) off that entry, excluding tickers
that already have an open ACTIVE position -> evaluates yesterday's
ACTIVE trades' T1/T2/T3 independently against today's live price for
Hold/Sell -> appends today's fresh Buy list.

v2: no more per-horizon loop — one scan, one ranked list, one Buy tab
write. "Horizon" survives only as a display label attached to each
target (see config.TARGET_HORIZON_LABEL), not as a scoring axis.

v3: score widened from /20 to /25 (added DSEX relative-strength + Low-
proximity criteria) — MIN_SCORE/SCORE_MAX come from config, nothing here
is hardcoded to the old /20 scale anymore.

Investment (long-term SIP) watchlist checks run as a SEPARATE script
(scripts/investment_check.py), as an additional GitHub Actions step right
after this one, not from inside this file — see that script's docstring.
"""
from datetime import date
from config import TOP_N_DAILY, MIN_BARS_REQUIRED, MIN_SCORE, SCORE_MAX
from market_calendar import is_market_holiday
from scan import scan_universe, build_setups
from risk_manager import rank_and_filter
from sheet_data_source import ingest_staging, ingest_local_backfill, ledger_diagnostics
from sheets_manager import open_sheet, overwrite_tab
from state_manager import (
    evaluate_active_trades, apply_status_updates, add_new_buys,
    get_active_tickers, ACTIVE_HEADER, VIEW_HEADER,
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

    # 1. Evaluate existing ACTIVE trades' T1/T2/T3 (independently) against
    #    today's live price -> Hold / Sell.
    hold_rows, sell_rows, status_updates = evaluate_active_trades(sheet)
    apply_status_updates(sheet, status_updates)
    overwrite_tab(sheet, "hold", VIEW_HEADER, hold_rows)
    overwrite_tab(sheet, "sell", VIEW_HEADER, sell_rows)

    # Read AFTER apply_status_updates, so a stock that fully closed today
    # (its last open target hit, or stopped out) is no longer considered
    # "active" and is free to be picked again if it still qualifies — only
    # genuinely still-open positions get excluded from today's fresh picks.
    active_tickers = get_active_tickers(sheet)
    print(f"[{run_date}] {len(active_tickers)} ticker(s) already have an "
          f"open ACTIVE position — excluded from today's new picks.")

    # 2. Scan config.TRADING_WATCHLIST — one composite score per stock.
    print(f"[{run_date}] Scanning TRADING_WATCHLIST...")
    scan_results = scan_universe(sheet)
    print(f"  {len(scan_results)} ticker(s) had enough history "
          f"(>= {MIN_BARS_REQUIRED} bars) and scored successfully.")

    all_setups = build_setups(scan_results, exclude=active_tickers)
    qualifying = [s for s in all_setups if s["valid"]]
    if all_setups:
        best = max(s["score"] for s in all_setups)
        print(f"  {len(qualifying)} of {len(all_setups)} eligible ticker(s) "
              f"scored >= {MIN_SCORE}/{SCORE_MAX}, best seen = {best}/{SCORE_MAX}.")
    else:
        print("  0 tickers eligible to score today (either already-active, "
              "or none had enough history).")

    # 3. Rank across the WHOLE list (no horizon split) and take the top N.
    buy_setups = rank_and_filter(all_setups, TOP_N_DAILY)
    buy_rows = add_new_buys(sheet, buy_setups, run_date)  # appends to ActiveTrades
    overwrite_tab(sheet, "buy", ACTIVE_HEADER, buy_rows)  # today's Buy view

    for s in buy_setups:
        print(f"  BUY: {s['ticker']} — score {s['score']}/{SCORE_MAX} "
              f"(technical {s['technical_total']}/{SCORE_MAX - 2} + SL {s['sl_quality']} "
              f"+ Target {s['target_quality']}), SL via {s['sl_source']} "
              f"({s['stop_loss']}), targets via {s['target_source']} "
              f"(T1={s['target_1']} T2={s['target_2']} T3={s['target_3']}).")
    print(f"  {len(buy_setups)} new Buy pick(s) added "
          f"(top {TOP_N_DAILY}, fewer if fewer cleared the bar).")

    print(f"[{run_date}] EOD run complete: {len(buy_rows)} buy row(s), "
          f"{len(hold_rows)} hold(s), {len(sell_rows)} sell(s).")


if _name_ == "_main_":
    main()
