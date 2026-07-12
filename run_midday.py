"""
12:15 PM run — mid-session check.

1. Re-checks live price on every ACTIVE trade so a stop-loss or target hit
   doesn't sit unflagged until the 3 PM run.
2. Surfaces the TOP_N_MIDDAY highest-scoring setups across ALL horizons
   combined as a same-day "running buy" signal.

Design note / assumption (not asked about, stated here instead): the
midday top picks are written ONLY to the Buy_Midday tab with status
SIGNAL_ONLY — they are NOT added to ActiveTrades. That keeps the 3 PM
run's official Buy list as the single place new positions get tracked, so
a stock flagged at midday and again at EOD isn't double-counted. If you'd
rather have midday picks tracked immediately, call state_manager.add_new_buys()
here instead of just writing the view — one line to change, flagged below.

Also: scoring here still uses the LAST COMPLETED session's close, not a
live intraday bar — DSE doesn't expose reliable intraday OHLC history, so
the "signal" is really "based on yesterday's close, does this still look
strong right now" rather than a fresh intraday recalculation.
"""
from datetime import date
from config import TOP_N_MIDDAY, HORIZONS
from market_calendar import is_market_holiday
from scan import scan_universe
from risk_manager import build_setup, rank_and_filter
from sheets_manager import open_sheet, overwrite_tab
from state_manager import evaluate_active_trades, apply_status_updates, VIEW_HEADER

MIDDAY_HEADER = ["ticker", "horizon", "entry_low", "entry_high", "stop_loss",
                  "target_1", "target_2", "rrr", "score", "date", "status"]


def main():
    run_date = date.today().isoformat()
    if is_market_holiday(run_date):
        print(f"[{run_date}] DSE holiday — midday run skipped.")
        return

    sheet = open_sheet()

    # 1. Intraday Hold/Sell check
    hold_rows, sell_rows, status_updates = evaluate_active_trades(sheet)
    apply_status_updates(sheet, status_updates)
    overwrite_tab(sheet, "hold", VIEW_HEADER, hold_rows)
    overwrite_tab(sheet, "sell", VIEW_HEADER, sell_rows)

    # 2. Combined top-N "running buy" signal across all horizons
    scored = scan_universe()
    all_setups = [
        build_setup(s["ticker"], s["close"], s["atr14"], s["score"], horizon)
        for horizon in HORIZONS
        for s in scored
    ]
    top_picks = rank_and_filter(all_setups, TOP_N_MIDDAY)

    rows = [[
        s["ticker"], s["horizon"], s["entry_low"], s["entry_high"],
        s["stop_loss"], s["target_1"], s["target_2"], s["rrr"], s["score"],
        run_date, "SIGNAL_ONLY",
    ] for s in top_picks]
    overwrite_tab(sheet, "buy_midday", MIDDAY_HEADER, rows)
    print(f"[{run_date}] Midday run complete: {len(top_picks)} signal(s) posted, "
          f"{len(hold_rows)} holds, {len(sell_rows)} sells re-checked.")


if __name__ == "__main__":
    main()
