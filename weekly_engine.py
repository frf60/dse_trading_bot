"""
Weekly-cadence engine for the COMBINED v1_45stc + v2_allstc model --
REPLACES the old Branch A/B regime-switching engine entirely.

Cadence difference from the old engine: the old Branch A/B model only
ever signaled on Thursday closes (by design, matching its own backtest).
This model's backtest (combined_v1_45stc_v2_allstc_final.py) signals on
ANY qualifying trading day, so this engine screens EVERY new trading day
since the last scan (a full Sun-Thu batch, once a week) rather than
picking out Thursdays only.

Entry: the trading day immediately AFTER the signal day, at that day's
OPEN (not Sunday's high, and not the signal day itself) -- exactly
_resolve_trade()'s `entry_idx = i + 1; entry_price = f.at[entry_idx,
"open"]` in the backtest. Most signals within a week's batch already
have their very next day's data in the SAME batch (e.g. a Monday signal
enters Tuesday, already pasted) and fill immediately; only a signal on
the ledger's latest available day has to wait in PendingWeekly for next
week's paste to supply the entry day.

Exit: single stop/target fixed at entry (35% target / 45% stop off
entry_price), checked against each day's HIGH/LOW same as the backtest
-- NOT the old model's closing-price day-count percentage ladder. Hard
time-exit at day 120 (that day's close) if neither stop nor target has
fired by then. No averaging-down (Branch-A-only mechanic, gone).

Dedup: v1_45stc + v2_allstc combined are capped at
MAX_COMBINED_ENTRIES_PER_MONTH per (symbol, calendar month) -- counting
every row ever entered that month (open, closed, or still pending),
v1_45stc taking priority on a same-day tie. Unlike the old engine, a
symbol CAN carry more than one concurrent open position; only the
monthly count is capped, matching the backtest's apply_cross_model_dedup.
"""
import pandas as pd
import numpy as np

from sheets_manager import get_tab, read_records, overwrite_tab, append_rows
from sheet_data_source import get_all_history
import weekly_config as wc

ACTIVE_HEADER = [
    "ticker", "model", "entry_price", "stop_price", "target_price",
    "entry_date", "last_evaluated_date", "status",
    "exit_price", "exit_date", "exit_reason",
    "last_price", "pnl_pct",
]
PENDING_HEADER = ["ticker", "model", "signal_date"]
STATE_HEADER = ["last_scanned_date"]
PREVIEW_HEADER = ["ticker", "model", "as_of_date", "rsi", "signal_strength"]


def _rsi(series, length=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - (100 / (1 + rs))).fillna(50)


def _get_state(sheet) -> str:
    ws = get_tab(sheet, "weekly_state", STATE_HEADER)
    vals = ws.get_all_values()
    if len(vals) < 2 or not vals[1] or not vals[1][0]:
        return None
    return vals[1][0]


def _set_state(sheet, last_scanned_date: str):
    ws = get_tab(sheet, "weekly_state", STATE_HEADER)
    ws.clear()
    ws.append_row(STATE_HEADER)
    ws.append_row([last_scanned_date])


def load_ledger(sheet):
    df = get_all_history(sheet)
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    all_dates = sorted(df["date"].unique())
    per_symbol = {sym: g.set_index("date").sort_index() for sym, g in df.groupby("ticker")}
    return per_symbol, all_dates


def _v2_is_excluded_symbol(sym: str) -> bool:
    """Static (whole-symbol) exclusions for v2_allstc: index, treasury
    bond, corporate bond/sukuk, mutual fund -- minus the two explicitly
    protected names. The dynamic sub-Tk5 exclusion lives in the feature
    signal condition itself (checked per day, not here)."""
    if sym in wc.V2_PROTECTED_SYMBOLS:
        return False
    if sym in wc.V2_INDEX_SYMBOLS:
        return True
    if wc.V2_TREASURY_BOND_PATTERN.match(sym):
        return True
    if sym in wc.V2_CORP_BOND_SUKUK_SYMBOLS:
        return True
    if sym in wc.V2_MUTUAL_FUND_SYMBOLS:
        return True
    return False


def _build_features_v1(h: pd.DataFrame) -> pd.DataFrame:
    f = pd.DataFrame(index=h.index)
    f["open"], f["high"], f["low"], f["close"] = h["open"], h["high"], h["low"], h["close"]
    f["rsi"] = _rsi(h["close"], wc.RSI_PERIOD)
    f["roll_high"] = h["high"].rolling(wc.V1_HIGH_LOOKBACK_DAYS,
                                        min_periods=wc.V1_HIGH_LOOKBACK_DAYS // 2).max()
    f["turnover20"] = (h["close"] * h["volume"]).rolling(20, min_periods=20).mean()
    f["pct_below_high"] = (f["roll_high"] - f["close"]) / f["roll_high"]
    f["signal"] = (
        f["rsi"].between(wc.V1_RSI_LOW, wc.V1_RSI_HIGH)
        & (f["pct_below_high"] >= wc.V1_BELOW_HIGH_MIN_PCT)
        & (f["turnover20"] >= wc.MIN_TURNOVER_20D)
    ).fillna(False)
    return f


def _build_features_v2(h: pd.DataFrame) -> pd.DataFrame:
    f = pd.DataFrame(index=h.index)
    f["open"], f["high"], f["low"], f["close"] = h["open"], h["high"], h["low"], h["close"]
    f["rsi"] = _rsi(h["close"], wc.RSI_PERIOD)
    f["close_lag"] = h["close"].shift(wc.V2_DROP_LOOKBACK_DAYS)
    f["retN"] = f["close"] / f["close_lag"] - 1
    f["turnover20"] = (h["close"] * h["volume"]).rolling(20, min_periods=20).mean()
    f["signal"] = (
        f["rsi"].between(wc.V2_RSI_LOW, wc.V2_RSI_HIGH)
        & (f["retN"] <= -wc.V2_DROP_MIN_PCT)
        & (f["turnover20"] >= wc.MIN_TURNOVER_20D)
        & (f["close"] >= wc.V2_MIN_PRICE)
    ).fillna(False)
    return f


def scan_new_candidates(sheet, per_symbol, all_dates, last_scanned_date, all_records):
    """Screens every new trading day since last_scanned_date (NOT just
    Thursdays) for both v1_45stc and v2_allstc signals, applies the
    combined monthly dedup cap, and queues survivors into PendingWeekly.
    Runs BEFORE fill_pending in run_weekly.py so a signal whose entry day
    is already in this same week's batch can fill in the same run."""
    date_pos = {d: i for i, d in enumerate(all_dates)}
    new_dates = [d for d in all_dates if last_scanned_date is None or d > last_scanned_date]
    if last_scanned_date is None and new_dates:
        new_dates = new_dates[-1:]  # first-ever run: only the latest day
    if not new_dates:
        return {"queued": 0, "reason": "no new trading day since last scan"}

    feats_v1 = {sym: _build_features_v1(per_symbol[sym]) for sym in wc.V1_UNIVERSE if sym in per_symbol}
    v2_universe = sorted(s for s in per_symbol if not _v2_is_excluded_symbol(s))
    feats_v2 = {sym: _build_features_v2(per_symbol[sym]) for sym in v2_universe}

    # Seed the monthly cap from EVERY row ever entered that month (active,
    # closed, AND still-pending) -- the backtest's dedup counts admitted
    # signals, not "currently open" ones, so a closed position still uses
    # up its month's slot.
    combined_count = {}
    for r in all_records:
        key = (r["ticker"], r["entry_date"][:7])
        combined_count[key] = combined_count.get(key, 0) + 1
    for r in read_records(sheet, "pending_weekly", PENDING_HEADER):
        key = (r["ticker"], r["signal_date"][:7])
        combined_count[key] = combined_count.get(key, 0) + 1

    raw_signals = []
    for d in new_dates:
        for sym, f in feats_v1.items():
            if d in f.index and bool(f.at[d, "signal"]):
                raw_signals.append((d, sym, "v1_45stc"))
        for sym, f in feats_v2.items():
            if d in f.index and bool(f.at[d, "signal"]):
                raw_signals.append((d, sym, "v2_allstc"))

    # v1_45stc wins a same (date, symbol) tie, matching PRIORITY_MODEL.
    raw_signals.sort(key=lambda s: (s[0], s[1], 0 if s[2] == wc.PRIORITY_MODEL else 1))

    queued = []
    for d, sym, model in raw_signals:
        key = (sym, d[:7])
        c = combined_count.get(key, 0)
        if c >= wc.MAX_COMBINED_ENTRIES_PER_MONTH:
            continue  # monthly cap for this symbol already used up -- discard
        combined_count[key] = c + 1
        queued.append([sym, model, d])

    if queued:
        append_rows(sheet, "pending_weekly", PENDING_HEADER, queued)
    return {"queued": len(queued), "days_scanned": len(new_dates),
            "v1_universe_size": len(feats_v1), "v2_universe_size": len(feats_v2)}


def fill_pending(sheet, per_symbol, all_dates):
    """Fills queued signals once their signal day's NEXT trading day's
    open is in the ledger -- usually the SAME run that queued them
    (within-week signals), occasionally next week's run (a signal on the
    ledger's last available day)."""
    date_pos = {d: i for i, d in enumerate(all_dates)}
    pending = read_records(sheet, "pending_weekly", PENDING_HEADER)

    still_pending, new_active_rows, filled_log = [], [], []
    for r in pending:
        sym, model, sig_date = r["ticker"], r["model"], r["signal_date"]
        if sig_date not in date_pos:
            still_pending.append(r)
            continue
        entry_idx = date_pos[sig_date] + 1
        if entry_idx >= len(all_dates):
            still_pending.append(r)  # signal day is the ledger's last day -- wait for next paste
            continue
        entry_date = all_dates[entry_idx]
        h = per_symbol.get(sym)
        if h is None or entry_date not in h.index:
            still_pending.append(r)
            continue

        entry_price = float(h.loc[entry_date, "open"])
        target_pct = wc.V1_TARGET_PCT if model == "v1_45stc" else wc.V2_TARGET_PCT
        stop_pct = wc.V1_STOP_PCT if model == "v1_45stc" else wc.V2_STOP_PCT
        stop_price = entry_price * (1 - stop_pct)
        target_price = entry_price * (1 + target_pct)

        new_active_rows.append([
            sym, model, round(entry_price, 2), round(stop_price, 2), round(target_price, 2),
            entry_date, entry_date, "ACTIVE", "", "", "",
            round(entry_price, 2), 0.0,
        ])
        filled_log.append({"ticker": sym, "model": model, "action": "opened",
                            "price": round(entry_price, 2), "date": entry_date})

    if new_active_rows:
        append_rows(sheet, "active_trades_weekly", ACTIVE_HEADER, new_active_rows)
    overwrite_tab(sheet, "pending_weekly", PENDING_HEADER,
                   [[r["ticker"], r["model"], r["signal_date"]] for r in still_pending])
    return {"filled": len(filled_log), "still_pending": len(still_pending), "log": filled_log}


def evaluate_active(sheet, per_symbol, all_dates):
    """Replays each ACTIVE row day-by-day against its OWN fixed
    stop_price/target_price, checked on that day's HIGH/LOW (matching the
    backtest's _resolve_trade exactly), with a hard time-exit at the
    model's max_hold_days (that day's CLOSE)."""
    date_pos = {d: i for i, d in enumerate(all_dates)}
    records = read_records(sheet, "active_trades_weekly", ACTIVE_HEADER)
    changed = False

    for r in records:
        if r.get("status") != "ACTIVE":
            continue
        sym, model = r["ticker"], r["model"]
        h = per_symbol.get(sym)
        if h is None:
            continue
        entry_date = r["entry_date"]
        last_eval = r["last_evaluated_date"]
        if last_eval not in date_pos or entry_date not in date_pos:
            continue
        entry_idx = date_pos[entry_date]
        start_idx = date_pos[last_eval] + 1
        stop_price = float(r["stop_price"])
        target_price = float(r["target_price"])
        entry_price = float(r["entry_price"])
        max_hold = wc.V1_MAX_HOLD_DAYS if model == "v1_45stc" else wc.V2_MAX_HOLD_DAYS

        # Backfill last_price/pnl_pct from the already-known last_evaluated_date
        # close, so the two display columns stay populated even on a run
        # where no NEW trading day has arrived since the last one.
        if last_eval in h.index:
            close0 = float(h.loc[last_eval, "close"])
            r["last_price"] = round(close0, 2)
            r["pnl_pct"] = round((close0 - entry_price) / entry_price * 100, 2)

        for day_idx in range(start_idx, len(all_dates)):
            dd = all_dates[day_idx]
            if dd not in h.index:
                continue
            day_number = day_idx - entry_idx  # offset from entry -- matches backtest's "offset"
            if day_number < 1:
                continue
            low = float(h.loc[dd, "low"])
            high = float(h.loc[dd, "high"])
            close = float(h.loc[dd, "close"])
            # last_price/pnl_pct always reflect the most recent close seen,
            # independent of whether stop/target/time-exit fires below.
            r["last_price"] = round(close, 2)
            r["pnl_pct"] = round((close - entry_price) / entry_price * 100, 2)

            if low <= stop_price:
                r.update(status="CLOSED", exit_price=round(stop_price, 2), exit_date=dd,
                          exit_reason="stop", last_evaluated_date=dd)
                changed = True
                break
            elif high >= target_price:
                r.update(status="CLOSED", exit_price=round(target_price, 2), exit_date=dd,
                          exit_reason="target", last_evaluated_date=dd)
                changed = True
                break
            elif day_number >= max_hold:
                r.update(status="CLOSED", exit_price=round(close, 2), exit_date=dd,
                          exit_reason=f"time({max_hold}d)", last_evaluated_date=dd)
                changed = True
                break
            else:
                r["last_evaluated_date"] = dd

    if changed or records:
        rows = [[r[k] for k in ACTIVE_HEADER] for r in records]
        overwrite_tab(sheet, "active_trades_weekly", ACTIVE_HEADER, rows)
    return records


def preview_today(sheet, per_symbol, all_dates):
    """INFORMATIONAL ONLY -- lists every ticker currently passing EITHER
    v1_45stc's or v2_allstc's signal condition as of the LATEST ingested
    close, whatever weekday that is.

    Unlike the old Branch A/B engine's preview_today() (which only made
    sense because that model was Thursday-gated and one branch at a
    time), this model has no day-of-week gating and both legs run in
    parallel -- so this preview is really just "what would
    scan_new_candidates find on the latest day", shown WITHOUT touching
    pending_weekly, the monthly dedup counters, or _get_state/_set_state.
    Purely a read-only look-ahead so you can see what's close to
    qualifying without waiting for the next actual scan.
    """
    if not all_dates:
        return {"as_of": None, "candidates": []}
    d = all_dates[-1]

    feats_v1 = {sym: _build_features_v1(per_symbol[sym]) for sym in wc.V1_UNIVERSE if sym in per_symbol}
    v2_universe = sorted(s for s in per_symbol if not _v2_is_excluded_symbol(s))
    feats_v2 = {sym: _build_features_v2(per_symbol[sym]) for sym in v2_universe}

    candidates = []
    for sym, f in feats_v1.items():
        if d in f.index and bool(f.at[d, "signal"]):
            candidates.append({"ticker": sym, "model": "v1_45stc", "as_of_date": d,
                                "rsi": round(float(f.at[d, "rsi"]), 2),
                                "signal_strength": round(float(f.at[d, "pct_below_high"]) * 100, 2)})
    for sym, f in feats_v2.items():
        if d in f.index and bool(f.at[d, "signal"]):
            candidates.append({"ticker": sym, "model": "v2_allstc", "as_of_date": d,
                                "rsi": round(float(f.at[d, "rsi"]), 2),
                                "signal_strength": round(float(f.at[d, "retN"]) * 100, 2)})

    overwrite_tab(sheet, "preview_weekly", PREVIEW_HEADER,
                  [[c["ticker"], c["model"], c["as_of_date"], c["rsi"], c["signal_strength"]]
                   for c in candidates])
    return {"as_of": d, "candidates": candidates}


def update_views(sheet, records, newly_filled=None):
    hold = [r for r in records if r["status"] == "ACTIVE"]
    sold = [r for r in records if r["status"] != "ACTIVE"]
    overwrite_tab(sheet, "hold_weekly", ACTIVE_HEADER, [[r[k] for k in ACTIVE_HEADER] for r in hold])
    overwrite_tab(sheet, "sell_weekly", ACTIVE_HEADER, [[r[k] for k in ACTIVE_HEADER] for r in sold])
    if newly_filled is not None:
        buy_rows = [r for r in newly_filled if r["action"] == "opened"]
        overwrite_tab(sheet, "buy_weekly", ["ticker", "model", "date", "price"],
                      [[r["ticker"], r["model"], r["date"], r["price"]] for r in buy_rows])
