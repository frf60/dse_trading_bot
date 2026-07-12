"""
The stateful heart of the system. ActiveTrades is the single source of
truth; the Buy/Hold/Sell tabs are just filtered *views* of it
rewritten every run.

Each row is keyed by (ticker, horizon, date_added) — NOT by ticker alone —
so the same stock can sit in more than one horizon's watchlist at once
(e.g. rank #1 for 7+ and #3 for 30+ simultaneously) and each copy closes
independently against its own SL/target.
"""
from datetime import datetime
from sheets_manager import read_records, overwrite_tab, append_rows
from sheet_data_source import get_live_price

ACTIVE_HEADER = [
    "ticker", "horizon", "entry_low", "entry_high", "stop_loss",
    "target_1", "target_2", "rrr", "score", "date_added", "status",
]
VIEW_HEADER = ["ticker", "horizon", "entry_low", "entry_high", "stop_loss",
               "target_1", "target_2", "rrr", "score", "date_added",
               "status", "live_price", "last_checked"]


def load_active_trades(sheet):
    records = read_records(sheet, "active_trades", ACTIVE_HEADER)
    return [r for r in records if r.get("status") == "ACTIVE"]


def add_new_buys(sheet, setups: list, run_date: str):
    """setups: output of risk_manager.rank_and_filter(). Appended with status ACTIVE."""
    rows = [[
        s["ticker"], s["horizon"], s["entry_low"], s["entry_high"],
        s["stop_loss"], s["target_1"], s["target_2"], s["rrr"], s["score"],
        run_date, "ACTIVE",
    ] for s in setups]
    append_rows(sheet, "active_trades", ACTIVE_HEADER, rows)
    return rows


def evaluate_active_trades(sheet):
    """
    Pulls a live price for every ACTIVE row and buckets each into Hold or
    Sell. Returns (hold_rows, sell_rows, status_updates) — state itself is
    only mutated by apply_status_updates(), so a run that dies partway
    through never leaves the ledger half-updated.
    """
    active = load_active_trades(sheet)
    hold_rows, sell_rows, status_updates = [], [], {}
    now = datetime.now().isoformat(timespec="minutes")

    for row in active:
        ticker = row["ticker"]
        try:
            live = get_live_price(sheet, ticker)
        except Exception:
            continue  # no fresh price entered yet — leave it ACTIVE, retry next run

        sl, t1 = float(row["stop_loss"]), float(row["target_1"])
        base = [row[k] for k in ACTIVE_HEADER]
        key = (ticker, row["horizon"], row["date_added"])

        if live <= sl:
            status_updates[key] = "CLOSED_SL"
            sell_rows.append(base[:-1] + ["CLOSED_SL", live, now])
        elif live >= t1:
            status_updates[key] = "CLOSED_PROFIT"
            sell_rows.append(base[:-1] + ["CLOSED_PROFIT", live, now])
        else:
            hold_rows.append(base + [live, now])

    return hold_rows, sell_rows, status_updates


def apply_status_updates(sheet, status_updates: dict):
    """The only place ActiveTrades status changes — rewrites the tab with CLOSED_* applied."""
    if not status_updates:
        return
    all_records = read_records(sheet, "active_trades", ACTIVE_HEADER)
    for r in all_records:
        key = (r["ticker"], r["horizon"], r["date_added"])
        if key in status_updates:
            r["status"] = status_updates[key]
    rows = [[r[k] for k in ACTIVE_HEADER] for r in all_records]
    overwrite_tab(sheet, "active_trades", ACTIVE_HEADER, rows)
