"""
The stateful heart of the system. ActiveTrades is the single source of
truth; the Buy/Hold/Sell tabs are just filtered *views* of it, rewritten
every run.

v3 (this revision): the old model kept one row per (ticker, horizon,
date_added) with its OWN target_1/target_2, because each horizon was a
separate score/setup. The new model has ONE row per (ticker, date_added)
-- a single entry, single stop-loss, and THREE independent targets
(T1/T2/T3) tracked off it (per your answer: "target T1/T2/T3 alada-alada
track hobe, ekta hit hole baki gulu active thakbe"):

  - Each of target_1_status / target_2_status / target_3_status starts
    ACTIVE and independently becomes TARGET_HIT the run its price level
    is reached -- hitting one does NOT touch the other two.
  - stop_loss is shared: if price falls to/through it, EVERY target that
    is still ACTIVE becomes SL_HIT in the same run (already-hit targets
    keep their TARGET_HIT status -- a stop-out doesn't undo a booked win).
  - The row's overall `status` is ACTIVE as long as at least one target
    is still ACTIVE, and flips to CLOSED the run the last one resolves
    (whether that's T3 finally hit, or the stop taking out whatever was
    left). CLOSED rows move to the Sell view; rows still ACTIVE (even if
    1 or 2 of their 3 targets already hit) stay in Hold so the position
    keeps being tracked until it's fully closed.
"""
from datetime import datetime
from sheets_manager import read_records, overwrite_tab, append_rows
from sheet_data_source import get_live_price
from risk_manager import TARGET_KEYS

ACTIVE_HEADER = [
    "ticker", "entry_low", "entry_high",
    "stop_loss", "sl_source",
    "target_1", "target_2", "target_3", "target_source",
    "target_1_status", "target_2_status", "target_3_status",
    "score", "technical_total", "sl_quality", "target_quality",
    "date_added", "status",
]
VIEW_HEADER = ACTIVE_HEADER + ["live_price", "last_checked"]

STATUS_ACTIVE = "ACTIVE"
STATUS_TARGET_HIT = "TARGET_HIT"
STATUS_SL_HIT = "SL_HIT"


def load_active_trades(sheet):
    records = read_records(sheet, "active_trades", ACTIVE_HEADER)
    return [r for r in records if r.get("status") == "ACTIVE"]


def get_active_tickers(sheet) -> set:
    """
    Tickers that already have an open position (status ACTIVE), regardless
    of how many of their 3 targets have already fired. Used so scan.py
    doesn't re-add a fresh Buy for a stock that's already being tracked --
    a different, not-yet-held stock takes that slot instead. Replaces the
    old per-horizon get_active_ticker_horizons(); there's only ever one
    open position per ticker now, not one per horizon.
    """
    return {r["ticker"] for r in load_active_trades(sheet)}


def add_new_buys(sheet, setups: list, run_date: str):
    """setups: output of risk_manager.rank_and_filter(). Appended with
    status ACTIVE and all three target statuses ACTIVE."""
    rows = [[
        s["ticker"], s["entry_low"], s["entry_high"],
        s["stop_loss"], s["sl_source"],
        s["target_1"], s["target_2"], s["target_3"], s["target_source"],
        STATUS_ACTIVE, STATUS_ACTIVE, STATUS_ACTIVE,
        s["score"], s["technical_total"], s["sl_quality"], s["target_quality"],
        run_date, "ACTIVE",
    ] for s in setups]
    append_rows(sheet, "active_trades", ACTIVE_HEADER, rows)
    return rows


def evaluate_active_trades(sheet):
    """
    Pulls a live price for every ACTIVE row and, independently per target,
    checks whether that target or the shared stop-loss has been reached.
    Returns (hold_rows, sell_rows, status_updates) -- state itself is only
    mutated by apply_status_updates(), so a run that dies partway through
    never leaves the ledger half-updated.

    hold_rows:  rows still ACTIVE overall (0-2 of their targets may have
                just flipped to TARGET_HIT this run -- they stay in Hold,
                still tracking the remaining target(s) against the same SL)
    sell_rows:  rows that just became fully CLOSED this run (either the
                stop wiped out every remaining target, or the last open
                target -- usually T3 -- was just hit)
    """
    active = load_active_trades(sheet)
    hold_rows, sell_rows, status_updates = [], [], {}
    now = datetime.now().isoformat(timespec="minutes")

    for row in active:
        ticker = row["ticker"]
        try:
            live = get_live_price(sheet, ticker)
        except Exception:
            continue  # no fresh price entered yet -- leave it ACTIVE, retry next run

        sl = float(row["stop_loss"])
        # keyed by the ACTUAL column name ("target_1_status", not "target_1"
        # -- that one holds the price!) so the update below can never clobber
        # the price columns.
        target_status = {f"{k}_status": row[f"{k}_status"] for k in TARGET_KEYS}
        touched = False

        if live <= sl:
            for k in TARGET_KEYS:
                col = f"{k}_status"
                if target_status[col] == STATUS_ACTIVE:
                    target_status[col] = STATUS_SL_HIT
                    touched = True
        else:
            for k in TARGET_KEYS:
                col = f"{k}_status"
                if target_status[col] == STATUS_ACTIVE and live >= float(row[k]):
                    target_status[col] = STATUS_TARGET_HIT
                    touched = True

        still_active = any(v == STATUS_ACTIVE for v in target_status.values())
        overall_status = "ACTIVE" if still_active else "CLOSED"

        updated_row = dict(row)
        updated_row.update(target_status)
        updated_row["status"] = overall_status
        out_row = [updated_row[k] for k in ACTIVE_HEADER] + [live, now]

        (hold_rows if still_active else sell_rows).append(out_row)

        if touched or overall_status != row["status"]:
            key = (ticker, row["date_added"])
            status_updates[key] = {**target_status, "status": overall_status}

    return hold_rows, sell_rows, status_updates


def apply_status_updates(sheet, status_updates: dict):
    """The only place ActiveTrades status changes -- rewrites the tab with
    the per-target and overall status changes from evaluate_active_trades()
    applied."""
    if not status_updates:
        return
    all_records = read_records(sheet, "active_trades", ACTIVE_HEADER)
    for r in all_records:
        key = (r["ticker"], r["date_added"])
        if key in status_updates:
            r.update(status_updates[key])
    rows = [[r[k] for k in ACTIVE_HEADER] for r in all_records]
    overwrite_tab(sheet, "active_trades", ACTIVE_HEADER, rows)
