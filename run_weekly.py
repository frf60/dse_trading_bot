"""
Entry point for the COMBINED regime-switching weekly pipeline (Branch A:
Sideways/Downtrend dip-buy, Branch B: Uptrend breakout -- replaces the old
daily model, Model F, and the earlier Branch-A-only weekly pipeline).

Weekly workflow:
  1. Every Friday, before 11:30 PM, paste the past week's rows (Sun-Thu,
     all tickers) into RawStaging with columns: Date, Scrip, Open, High,
     Low, Close, Volume.
  2. This runs automatically at 11:30 PM Friday (GitHub Action), or run
     it manually any time after pasting.
  3. That Thursday's regime (idx_ret10 vs +1.5%) picks exactly ONE branch
     for that week -- Branch A on Sideways/Downtrend weeks, Branch B on
     Uptrend weeks. Both branches can now produce a Buy/PendingSignals
     entry; a week is only empty if no candidate cleared that branch's
     own screen (not an error -- see combined_regime_model.py's docstring).
"""
from sheets_manager import open_sheet
from sheet_data_source import ingest_staging
import weekly_engine as we


def main():
    sheet = open_sheet()

    ingest_result = ingest_staging(sheet)
    print(f"[1/5] Ingested from RawStaging: {ingest_result}")

    per_symbol, all_dates = we.load_ledger(sheet)
    if not all_dates:
        print("No price history in RawDailyPrices yet -- nothing to do.")
        return
    latest_date = all_dates[-1]
    print(f"[2/5] Ledger loaded: {len(all_dates)} trading days, latest = {latest_date}, "
          f"{len(per_symbol)} tickers")

    fill_result = we.fill_pending(sheet, per_symbol, all_dates)
    print(f"[3/5] Filled pending signals: {fill_result['filled']} "
          f"({fill_result['still_pending']} still waiting on next week's Sunday data)")
    for entry in fill_result["log"]:
        print(f"       {entry['action']}: {entry['ticker']} @ {entry['price']} on {entry['date']}")

    records = we.evaluate_active(sheet, per_symbol, all_dates)
    print(f"[4/5] Evaluated open positions: "
          f"{sum(1 for r in records if r['status']=='ACTIVE')} still in Hold, "
          f"{sum(1 for r in records if r['status']!='ACTIVE')} closed (lifetime total)")

    last_scanned = we._get_state(sheet)
    scan_result = we.scan_new_candidates(sheet, per_symbol, all_dates, last_scanned, records)
    we._set_state(sheet, latest_date)
    print(f"[5/5] Scanned for new Thursday signals since {last_scanned or '(first run)'}: "
          f"{scan_result}")

    we.update_views(sheet, records, newly_filled=fill_result["log"])


if __name__ == "__main__":
    main()
