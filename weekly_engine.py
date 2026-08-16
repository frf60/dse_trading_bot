"""
Weekly-cadence engine for the COMBINED regime-switching model (Branch A:
Sideways/Downtrend dip-buy, Branch B: Uptrend breakout) -- replaces the
old Branch-A-only engine, the earlier daily model, and Model F.

Cadence: screens only on Thursday closes. That Thursday's regime decides
which SINGLE branch is eligible (see _is_uptrend_series / regime switch
below) -- exactly matches combined_regime_model.py, so the live pipeline
and the backtest agree by construction. A signal queues into
PendingSignals until the following Sunday's OHLC arrives (next week's
paste), then fills at that Sunday's HIGH. Exit is a day-count ladder
checked on CLOSING price vs entry (or blended, for Branch A only) --
replayed day by day as each week's data comes in, so it matches the
backtest exactly regardless of cadence. Each row's OWN branch decides
which exit ladder applies (price_window_exit_check_a vs _b).

Averaging-down (Branch A ONLY): if a fresh Thursday Branch-A signal names
a symbol that already has an open Branch-A position, it's normally
discarded (one position per symbol) -- UNLESS that position is past day
10 and its unrealized return is between -20% and -15%, in which case the
signal is used to average down once (blended price = mean of original
entry and the new signal's Sunday high; day-count keeps counting from the
ORIGINAL entry). Branch B never averages down.
"""
import pandas as pd
import numpy as np

from sheets_manager import get_tab, read_records, overwrite_tab, append_rows
from sheet_data_source import ingest_staging, get_all_history
import weekly_config as wc

# "branch" (A/B) now threads through every row so exits/averaging use the
# right per-branch rule even though both branches share these tabs.
ACTIVE_HEADER = [
    "ticker", "branch", "entry_price", "current_price", "averaged", "avg_date",
    "entry_date", "last_evaluated_date", "status",
    "exit_price", "exit_date", "exit_reason",
]
PENDING_HEADER = ["ticker", "branch", "signal_date", "kind", "rank_metric"]  # kind: NEW or AVERAGE
STATE_HEADER = ["last_scanned_date"]


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


def price_window_exit_check_a(ret_pct, day_number):
    if day_number < 3:
        return False
    if 3 <= day_number <= 20:
        return ret_pct >= 15
    if 21 <= day_number <= 40:
        return ret_pct >= 10
    if 41 <= day_number <= 60:
        return ret_pct >= 5
    if 61 <= day_number <= 80:
        return ret_pct >= 2
    if 81 <= day_number <= 90:
        return ret_pct >= -2
    if 91 <= day_number <= 119:
        return ret_pct >= -4
    return ret_pct >= -15  # day 120+: hard stop-loss floor


def price_window_exit_check_b(ret_pct, day_number):
    if day_number < 3:
        return False
    if 3 <= day_number <= 15:
        return ret_pct >= 20
    if 16 <= day_number <= 30:
        return ret_pct >= 12
    if 31 <= day_number <= 60:
        return ret_pct >= 5
    if 61 <= day_number <= 90:
        return ret_pct >= 0
    if 91 <= day_number <= 119:
        return ret_pct >= -5
    return ret_pct >= -10  # day 120+: hard stop-loss floor


def _exit_check(branch, ret_pct, day_number):
    return price_window_exit_check_a(ret_pct, day_number) if branch == "A" \
        else price_window_exit_check_b(ret_pct, day_number)


def load_ledger(sheet):
    df = get_all_history(sheet)
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    all_dates = sorted(df["date"].unique())
    per_symbol = {sym: g.set_index("date").sort_index() for sym, g in df.groupby("ticker")}
    return per_symbol, all_dates


def _is_uptrend_series(per_symbol):
    if wc.INDEX_SYMBOL not in per_symbol:
        return pd.Series(dtype=bool)
    dsex_close = per_symbol[wc.INDEX_SYMBOL]["close"]
    idx_ret10 = dsex_close.pct_change(wc.REGIME_LOOKBACK_DAYS)
    return idx_ret10 >= wc.REGIME_UP_THRESHOLD


def _build_features_a(per_symbol):
    dsex_close = per_symbol[wc.INDEX_SYMBOL]["close"]
    idx_ret20 = dsex_close.pct_change(wc.RELSTRENGTH_LOOKBACK_DAYS)
    feats = {}
    for sym in wc.TICKERS:
        if sym not in per_symbol:
            continue
        h = per_symbol[sym]
        f = pd.DataFrame(index=h.index)
        f["close"] = h["close"]
        f["rsi"] = _rsi(h["close"], wc.RSI_PERIOD)
        f["roll_low60"] = h["low"].rolling(wc.LOOKBACK_LOW_DAYS, min_periods=wc.LOOKBACK_LOW_DAYS // 3).min()
        f["turnover20"] = (h["volume"] * h["close"]).rolling(20, min_periods=20).mean()
        f["ret20"] = h["close"].pct_change(wc.RELSTRENGTH_LOOKBACK_DAYS)
        f["vol20"] = h["close"].pct_change().rolling(20, min_periods=15).std() * 100
        feats[sym] = f
    return feats, idx_ret20


def _build_features_b(per_symbol):
    feats = {}
    for sym in wc.TICKERS:
        if sym not in per_symbol:
            continue
        h = per_symbol[sym]
        f = pd.DataFrame(index=h.index)
        f["open"] = h["open"]
        f["close"] = h["close"]
        f["volume"] = h["volume"]
        f["volume_prev"] = h["volume"].shift(1)
        f["rsi"] = _rsi(h["close"], wc.B_RSI_PERIOD)
        f["rsi_prev"] = f["rsi"].shift(1)
        f["vol20_frac"] = h["close"].pct_change().rolling(20, min_periods=15).std()
        f["vol_ema20"] = h["volume"].ewm(span=20, adjust=False).mean()
        f["vol_ratio"] = h["volume"] / f["vol_ema20"]
        feats[sym] = f
    return feats


def fill_pending(sheet, per_symbol, all_dates):
    """Fills queued NEW/AVERAGE signals once their Sunday's HIGH is in the ledger."""
    date_pos = {d: i for i, d in enumerate(all_dates)}
    pending = read_records(sheet, "pending_weekly", PENDING_HEADER)
    active = read_records(sheet, "active_trades_weekly", ACTIVE_HEADER)
    active_by_ticker = {(r["ticker"], r["branch"]): r for r in active if r.get("status") == "ACTIVE"}

    still_pending, new_active_rows, filled_log = [], [], []
    for r in pending:
        sym, branch, sig_date, kind = r["ticker"], r["branch"], r["signal_date"], r["kind"]
        if sig_date not in date_pos:
            still_pending.append(r)
            continue
        entry_idx = date_pos[sig_date] + 1
        if entry_idx >= len(all_dates):
            still_pending.append(r)
            continue
        entry_date = all_dates[entry_idx]
        h = per_symbol.get(sym)
        if h is None or entry_date not in h.index:
            still_pending.append(r)
            continue
        fill_high = float(h.loc[entry_date, "high"])

        if kind == "NEW":
            new_active_rows.append([
                sym, branch, round(fill_high, 2), round(fill_high, 2), False, "",
                entry_date, entry_date, "ACTIVE", "", "", "",
            ])
            filled_log.append({"ticker": sym, "branch": branch, "action": "opened",
                                "price": fill_high, "date": entry_date})
        elif kind == "AVERAGE":  # Branch A only, by construction (see scan_new_candidates)
            existing = active_by_ticker.get((sym, branch))
            if existing and existing.get("status") == "ACTIVE" and existing.get("averaged") != "True":
                orig_entry = float(existing["entry_price"])
                blended = (orig_entry + fill_high) / 2
                for row in active:
                    if row is existing:
                        row["current_price"] = round(blended, 2)
                        row["averaged"] = True
                        row["avg_date"] = entry_date
                filled_log.append({"ticker": sym, "branch": branch, "action": "averaged",
                                    "price": fill_high, "date": entry_date})
            # else: position already closed/averaged/gone -- signal just discarded

    if new_active_rows:
        append_rows(sheet, "active_trades_weekly", ACTIVE_HEADER, new_active_rows)
    if any(r.get("action") == "averaged" for r in filled_log):
        overwrite_tab(sheet, "active_trades_weekly", ACTIVE_HEADER,
                       [[row[k] for k in ACTIVE_HEADER] for row in active])
    overwrite_tab(sheet, "pending_weekly", PENDING_HEADER,
                   [[r["ticker"], r["branch"], r["signal_date"], r["kind"], r["rank_metric"]] for r in still_pending])
    return {"filled": len(filled_log), "still_pending": len(still_pending), "log": filled_log}


def evaluate_active(sheet, per_symbol, all_dates):
    """Replays each ACTIVE row day-by-day on CLOSING price vs its
    entry/blended price, applying that row's OWN branch's day-count
    ladder. day_number always counts from the ORIGINAL entry_date, even
    after a Branch-A average-down."""
    date_pos = {d: i for i, d in enumerate(all_dates)}
    records = read_records(sheet, "active_trades_weekly", ACTIVE_HEADER)
    changed = False

    for r in records:
        if r.get("status") != "ACTIVE":
            continue
        sym = r["ticker"]
        branch = r.get("branch") or "A"
        h = per_symbol.get(sym)
        if h is None:
            continue
        current_price = float(r["current_price"])
        entry_date = r["entry_date"]
        last_eval = r["last_evaluated_date"]
        if last_eval not in date_pos or entry_date not in date_pos:
            continue
        entry_idx = date_pos[entry_date]
        start_idx = date_pos[last_eval] + 1

        for day_idx in range(start_idx, len(all_dates)):
            dd = all_dates[day_idx]
            if dd not in h.index:
                continue
            day_number = (day_idx - entry_idx) + 1
            close = float(h.loc[dd, "close"])
            ret_pct = (close - current_price) / current_price * 100

            if _exit_check(branch, ret_pct, day_number):
                r.update(status="CLOSED", exit_price=round(close, 2), exit_date=dd,
                         exit_reason=f"price-window (ret={round(ret_pct, 2)}%)", last_evaluated_date=dd)
                changed = True
                break
            else:
                r["last_evaluated_date"] = dd

    if changed or records:
        rows = [[r[k] for k in ACTIVE_HEADER] for r in records]
        overwrite_tab(sheet, "active_trades_weekly", ACTIVE_HEADER, rows)
    return records


def scan_new_candidates(sheet, per_symbol, all_dates, last_scanned_date, active_records):
    """Screens only NEW Thursday closes since last_scanned_date. For each
    Thursday, that day's regime picks exactly ONE branch (matches
    combined_regime_model.py's select_weekly): UPTREND -> Branch B's
    highest-vol_ratio candidate; NOT-UPTREND -> Branch A's most-negative-
    RelStrength20 candidate. Then decides NEW vs AVERAGE (Branch A only)
    vs discard against the CURRENT active-position state for that branch."""
    if wc.INDEX_SYMBOL not in per_symbol:
        return {"queued": 0, "reason": f"{wc.INDEX_SYMBOL} missing from ledger"}

    weekday_of = {d: pd.Timestamp(d).weekday() for d in all_dates}
    thursdays = [d for d in all_dates if weekday_of[d] == 3
                 and (last_scanned_date is None or d > last_scanned_date)]
    if last_scanned_date is None and thursdays:
        thursdays = thursdays[-1:]  # first-ever run: only the latest Thursday
    if not thursdays:
        return {"queued": 0, "reason": "no new Thursday close since last scan"}

    is_uptrend = _is_uptrend_series(per_symbol)
    feats_a, idx_ret20 = _build_features_a(per_symbol)
    feats_b = _build_features_b(per_symbol)
    date_pos = {d: i for i, d in enumerate(all_dates)}
    active_by_ticker = {(r["ticker"], r.get("branch")): r for r in active_records if r.get("status") == "ACTIVE"}

    queued = []
    regime_log = []
    for d in thursdays:
        if date_pos[d] < wc.MIN_BARS_REQUIRED:
            continue
        up = bool(is_uptrend.get(d, False))
        branch = "B" if up else "A"
        regime_log.append((d, branch))

        if branch == "A":
            if d not in idx_ret20.index or pd.isna(idx_ret20.loc[d]):
                continue
            candidates = []
            for sym, f in feats_a.items():
                if d not in f.index:
                    continue
                row = f.loc[d]
                if row[["rsi", "roll_low60", "turnover20", "ret20", "vol20"]].isna().any():
                    continue
                if row["turnover20"] < wc.MIN_TURNOVER_20D or row["vol20"] < wc.MIN_VOL20_PCT:
                    continue
                if not (wc.RSI_MIN < row["rsi"] < wc.RSI_MAX):
                    continue
                prox_pct = (row["close"] - row["roll_low60"]) / row["roll_low60"] * 100
                if prox_pct > wc.PROXIMITY_TO_LOW_MAX_PCT:
                    continue
                rel = row["ret20"] - idx_ret20.loc[d]
                if not (rel < wc.RS_ELIGIBILITY_MAX):
                    continue
                candidates.append((sym, rel))
            if not candidates:
                continue
            candidates.sort(key=lambda x: x[1])  # most negative first
            top_sym, top_rank = candidates[0]

            existing = active_by_ticker.get((top_sym, "A"))
            if existing is None:
                queued.append([top_sym, "A", d, "NEW", round(float(top_rank), 4)])
            else:
                entry_idx = date_pos[existing["entry_date"]]
                day_number = (date_pos[d] - entry_idx) + 1
                cur_price = float(existing["current_price"])
                h = per_symbol.get(top_sym)
                ret_pct = (float(h.loc[d, "close"]) - cur_price) / cur_price * 100 if h is not None and d in h.index else None
                already_averaged = existing.get("averaged") in (True, "True")
                if (not already_averaged and ret_pct is not None and day_number > wc.AVERAGE_MIN_DAY
                        and wc.AVERAGE_BAND_LO <= ret_pct <= wc.AVERAGE_BAND_HI):
                    queued.append([top_sym, "A", d, "AVERAGE", round(float(top_rank), 4)])
                # else: symbol already has an open Branch-A position outside the
                # averaging window -- signal is discarded, matching the backtest.

        else:  # branch == "B"
            candidates = []
            for sym, f in feats_b.items():
                if d not in f.index:
                    continue
                row = f.loc[d]
                if row[["rsi", "rsi_prev", "vol20_frac", "vol_ema20", "volume_prev"]].isna().any():
                    continue
                if row["vol20_frac"] < wc.B_MIN_VOL20_FRAC:
                    continue
                if not (wc.B_RSI_LO <= row["rsi"] <= wc.B_RSI_HI and row["rsi_prev"] < wc.B_RSI_LO):
                    continue
                if row["vol_ratio"] < wc.B_VOL_MULT:
                    continue
                if not (row["close"] > row["open"] and row["volume"] > row["volume_prev"]):
                    continue
                candidates.append((sym, row["vol_ratio"]))
            if not candidates:
                continue
            candidates.sort(key=lambda x: x[1], reverse=True)  # highest vol_ratio first
            top_sym, top_rank = candidates[0]

            existing = active_by_ticker.get((top_sym, "B"))
            if existing is None:
                queued.append([top_sym, "B", d, "NEW", round(float(top_rank), 4)])
            # else: Branch B never averages down -- a signal on an already-open
            # Branch-B symbol is simply discarded (one position per symbol).

    if queued:
        append_rows(sheet, "pending_weekly", PENDING_HEADER, queued)
    return {"queued": len(queued), "regime_by_thursday": regime_log}


def update_views(sheet, records, newly_filled=None):
    hold = [r for r in records if r["status"] == "ACTIVE"]
    sold = [r for r in records if r["status"] != "ACTIVE"]
    overwrite_tab(sheet, "hold_weekly", ACTIVE_HEADER, [[r[k] for k in ACTIVE_HEADER] for r in hold])
    overwrite_tab(sheet, "sell_weekly", ACTIVE_HEADER, [[r[k] for k in ACTIVE_HEADER] for r in sold])
    if newly_filled is not None:
        buy_rows = [r for r in newly_filled if r["action"] == "opened"]
        overwrite_tab(sheet, "buy_weekly", ["ticker", "branch", "date", "price"],
                      [[r["ticker"], r["branch"], r["date"], r["price"]] for r in buy_rows])
