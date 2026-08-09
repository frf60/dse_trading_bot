"""
selective_signal.py
====================
Third engine, parallel to the /25-score trading engine and the Investment
tab. Reuses sheet_data_source.get_historical_data() (now needs 'open' —
see patch_sheet_data_source.md) and the same RawDailyPrices ledger, but
keeps its OWN state (SS_Candidates / SS_Active / SS_Sell tabs) because its
lifecycle (T+2 lock, hard 15-trading-day cap, single stop/target) doesn't
fit ActiveTrades' 3-independent-target model.

Two things happen each daily run (call both from run_eod.py, AFTER
ingest_staging() so the day's row is already in RawDailyPrices):

  1. scan_and_accumulate(sheet, run_date)
       Screens SELECTIVE_SIGNAL_WATCHLIST for today's date, appends any
       new qualifying (ticker, date, relstrength20) rows to SS_Candidates
       for the CURRENT calendar month. Idempotent per (ticker, month): a
       ticker that already has a signal recorded this month is not added
       again (mirrors the T2 script's "earliest signal per symbol per
       month" behaviour).

  2. resolve_month_end_and_enter(sheet, run_date)
       On the LAST trading day the pipeline processes for a given month
       (see note in that function — you decide the trigger), ranks
       SS_Candidates for that month by relstrength20, takes the top
       SS_TOP_N_PER_MONTH, and opens a position for each (skipping any
       ticker already open in SS_Active) using the NEXT trading day's
       open once it arrives.

     Simpler alternative used below instead of a month-end trigger:
     evaluate the running top-N EVERY day and enter a signal the day
     after it first cracks the current top-N list. This trades a small
     amount of within-month lookahead (same simplification the July
     re-run backtest used) for not needing to detect "last day of month"
     in a pipeline that runs once daily and can be triggered manually.

  3. update_active_positions(sheet, run_date)
       For every SS_Active row: figure out how many trading days have
       elapsed since entry (by counting rows in RawDailyPrices, NOT
       calendar days — weekends/holidays are never pasted so this is
       already a trading-day count), then:
         - offset 0,1 (T, T+1): locked, no exit possible even if the
           day's low/high breached stop/target (flag gap_risk if so).
         - offset 2..13: exit if low <= stop_loss (loss) or
           high >= target (win); stop wins if both same day.
         - offset 14 (day 15): force exit at that day's close no matter
           what (this is the fix for the earlier 16-day-hold bug).
"""
from datetime import date
from collections import defaultdict

from config import (
    SELECTIVE_SIGNAL_WATCHLIST, INDEX_TICKER,
    SS_RSI_PERIOD, SS_RSI_MAX, SS_LOOKBACK_LOW_DAYS, SS_PROXIMITY_TO_LOW_MAX_PCT,
    SS_MIN_TURNOVER_20D, SS_RELSTRENGTH_LOOKBACK_DAYS, SS_TOP_N_PER_MONTH,
    SS_STOP_PCT, SS_TARGET_PCT, SS_T2_LOCK_DAYS, SS_MAX_HOLD_DAYS,
    SS_MIN_BARS_REQUIRED, SS_STAKE_PER_TRADE,
)
from sheet_data_source import get_historical_data
from sheets_manager import read_records, append_rows, overwrite_tab
from indicators import rsi  # reuse the same RSI implementation everywhere

CAND_HEADER = ["month", "ticker", "signal_date", "relstrength20"]
ACTIVE_HEADER = [
    "ticker", "signal_date", "entry_date", "fill_price",
    "stop_loss", "target", "gap_risk", "date_added",
]
SELL_HEADER = ACTIVE_HEADER + [
    "exit_date", "exit_price", "outcome", "r_multiple",
    "hold_trading_days", "pnl_per_stake", "exit_reason",
]


# --------------------------------------------------------------------
# 1. Daily screen -> accumulate this month's candidates
# --------------------------------------------------------------------
def _passes_screen(hist, index_positive_ret20):
    """hist: get_historical_data() output for one ticker, ending today.
    Returns the candidate dict or None if it doesn't qualify."""
    if len(hist) < SS_MIN_BARS_REQUIRED:
        return None
    close = hist["close"]
    rsi_now = float(rsi(close, SS_RSI_PERIOD).iloc[-1])
    roll_low = hist["low"].tail(SS_LOOKBACK_LOW_DAYS).min()
    close_now = float(close.iloc[-1])
    prox_pct = (close_now - roll_low) / roll_low * 100
    turnover20 = (hist["volume"] * hist["close"]).tail(20).mean()
    if turnover20 < SS_MIN_TURNOVER_20D:
        return None
    if not (rsi_now <= SS_RSI_MAX and prox_pct <= SS_PROXIMITY_TO_LOW_MAX_PCT):
        return None
    stock_ret20 = close.pct_change(SS_RELSTRENGTH_LOOKBACK_DAYS).iloc[-1]
    return {"relstrength20": stock_ret20 - index_positive_ret20}


def scan_and_accumulate(sheet, run_date: str = None):
    run_date = run_date or date.today().isoformat()
    month = run_date[:7]

    index_hist = get_historical_data(sheet, INDEX_TICKER)
    if index_hist is None or len(index_hist) < SS_RELSTRENGTH_LOOKBACK_DAYS + 1:
        print(f"  [selective_signal] {INDEX_TICKER}: not enough history for "
              f"relative-strength yet — skipping today's scan.")
        return {"scanned": 0, "new_candidates": 0}
    idx_ret20 = float(index_hist["close"].pct_change(SS_RELSTRENGTH_LOOKBACK_DAYS).iloc[-1])

    existing = read_records(sheet, "ss_candidates", CAND_HEADER)
    already_this_month = {r["ticker"] for r in existing if r["month"] == month}

    new_rows = []
    for ticker in SELECTIVE_SIGNAL_WATCHLIST:
        if ticker in already_this_month:
            continue  # one signal per ticker per month (earliest wins)
        try:
            hist = get_historical_data(sheet, ticker)
        except Exception:
            continue
        cand = _passes_screen(hist, idx_ret20)
        if cand is not None:
            new_rows.append([month, ticker, run_date, round(cand["relstrength20"], 5)])

    if new_rows:
        append_rows(sheet, "ss_candidates", CAND_HEADER, new_rows)
    return {"scanned": len(SELECTIVE_SIGNAL_WATCHLIST), "new_candidates": len(new_rows)}


# --------------------------------------------------------------------
# 2. Enter positions for anything currently in the running top-N
# --------------------------------------------------------------------
def enter_top_n_signals(sheet, run_date: str = None):
    """
    Call AFTER scan_and_accumulate() in the same run. Looks at the current
    month's candidates, takes the top SS_TOP_N_PER_MONTH by relstrength20,
    and opens a position (at TODAY's open, since today's row is already
    in the ledger and yesterday was signal day) for any that:
      - aren't already in SS_Active (open or historically entered this
        month — a ticker only signals once/month anyway), and
      - have a signal_date strictly before run_date (need a "next day"
        to fill at).
    """
    run_date = run_date or date.today().isoformat()
    month = run_date[:7]

    candidates = [r for r in read_records(sheet, "ss_candidates", CAND_HEADER)
                  if r["month"] == month]
    candidates.sort(key=lambda r: float(r["relstrength20"]), reverse=True)
    top_n = candidates[:SS_TOP_N_PER_MONTH]

    active = read_records(sheet, "ss_active", ACTIVE_HEADER)
    open_tickers = {r["ticker"] for r in active}

    new_rows = []
    for c in top_n:
        ticker = c["ticker"]
        if ticker in open_tickers or c["signal_date"] >= run_date:
            continue
        try:
            hist = get_historical_data(sheet, ticker)
        except Exception:
            continue
        if hist.empty or run_date not in hist.index.astype(str):
            continue  # today's row must already be in the ledger to fill at today's open
        fill_price = float(hist.loc[run_date, "open"])
        stop_loss = round(fill_price * (1 - SS_STOP_PCT), 2)
        target = round(fill_price * (1 + SS_TARGET_PCT), 2)
        new_rows.append([
            ticker, c["signal_date"], run_date, fill_price,
            stop_loss, target, "No", run_date,
        ])
        open_tickers.add(ticker)

    if new_rows:
        append_rows(sheet, "ss_active", ACTIVE_HEADER, new_rows)
    return {"entered": len(new_rows)}


# --------------------------------------------------------------------
# 3. Update open positions: T+2 lock, stop/target, hard 15-day cap
# --------------------------------------------------------------------
def _trading_days_elapsed(hist, entry_date: str) -> int:
    """Count of trading days STRICTLY AFTER entry_date present in hist's
    index, up to and including today. hist is already date-sorted."""
    dates = list(hist.index.astype(str))
    if entry_date not in dates:
        return 0
    return len(dates) - 1 - dates.index(entry_date)


def update_active_positions(sheet, run_date: str = None):
    run_date = run_date or date.today().isoformat()
    active = read_records(sheet, "ss_active", ACTIVE_HEADER)
    if not active:
        return {"checked": 0, "closed": 0}

    still_open, closed = [], []
    for row in active:
        ticker = row["ticker"]
        try:
            hist = get_historical_data(sheet, ticker)
        except Exception:
            still_open.append(row)
            continue

        entry_date = row["entry_date"]
        fill_price = float(row["fill_price"])
        stop_loss = float(row["stop_loss"])
        target = float(row["target"])
        offset = _trading_days_elapsed(hist, entry_date)

        if entry_date not in hist.index.astype(str) or run_date not in hist.index.astype(str):
            still_open.append(row)
            continue
        today = hist.loc[run_date]

        if offset < SS_T2_LOCK_DAYS:
            if today["low"] <= stop_loss:
                row["gap_risk"] = "Yes"
            still_open.append(row)
            continue

        exit_price = outcome = exit_reason = None
        if today["low"] <= stop_loss:
            exit_price, outcome, exit_reason = stop_loss, "loss", "stop"
        elif today["high"] >= target:
            exit_price, outcome, exit_reason = target, "win", "target"
        elif offset >= SS_MAX_HOLD_DAYS - 1:
            exit_price = float(today["close"])
            outcome = "win" if exit_price > fill_price else "loss"
            exit_reason = "time (day15)"

        if exit_price is None:
            still_open.append(row)
            continue

        r_multiple = ((exit_price - fill_price) / fill_price) / SS_STOP_PCT
        pnl = r_multiple * SS_STOP_PCT * SS_STAKE_PER_TRADE
        closed.append([*(row[k] for k in ACTIVE_HEADER),
                        run_date, round(exit_price, 2), outcome, round(r_multiple, 3),
                        offset, round(pnl, 0), exit_reason])

    overwrite_tab(sheet, "ss_active", ACTIVE_HEADER, [[r[k] for k in ACTIVE_HEADER] for r in still_open])
    if closed:
        append_rows(sheet, "ss_sell", SELL_HEADER, closed)
    return {"checked": len(active), "closed": len(closed)}


def run_selective_signal_pipeline(sheet, run_date: str = None):
    """Convenience wrapper — call this one function from run_eod.py."""
    run_date = run_date or date.today().isoformat()
    scan_stats = scan_and_accumulate(sheet, run_date)
    enter_stats = enter_top_n_signals(sheet, run_date)
    update_stats = update_active_positions(sheet, run_date)
    print(f"  [selective_signal] scanned {scan_stats['scanned']}, "
          f"+{scan_stats['new_candidates']} new candidates, "
          f"{enter_stats['entered']} entered, {update_stats['closed']} closed")
    return {**scan_stats, **enter_stats, **update_stats}
