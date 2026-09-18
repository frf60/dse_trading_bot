"""
Entry point for the COMBINED v1_45stc + v2_allstc weekly pipeline --
REPLACES the old Branch A/B regime-switching pipeline entirely.

Weekly workflow:
  1. Every Friday, before 11:30 PM, paste the past week's rows (Sun-Thu,
     all tickers) into RawStaging with columns: Date, Scrip, Open, High,
     Low, Close, Volume.
  2. This runs automatically at 11:30 PM Friday (GitHub Action), or run
     it manually any time after pasting.
  3. Every new trading day in that batch is screened for BOTH v1_45stc
     (fixed 45-stock dip-below-30-day-high) and v2_allstc (broad-universe
     sharp-drop) signals -- not gated to one day a week like the old
     Branch A/B model was. A signal enters at the NEXT trading day's
     OPEN: most of the week's signals already have that next day in the
     SAME batch and fill immediately; only a signal on the batch's very
     last day waits in PendingWeekly for next week's paste.

BUYING INSTRUCTION CHANGED from the old model: buy at the entry day's
OPEN price shown in BuyWeekly, not the day's high.

Order matters: scan BEFORE fill, so a signal detected this run can fill
in this SAME run if its entry day's data already arrived in this week's
paste. Step 6 (Preview) is read-only and informational -- it shows every
ticker currently passing either leg's screen as of the latest ingested
close, without queuing anything or touching scan state.
"""
from sheets_manager import open_sheet, read_records
from sheet_data_source import ingest_staging
import weekly_engine as we


def main():
    sheet = open_sheet()

    ingest_result = ingest_staging(sheet)
    print(f"[1/6] Ingested from RawStaging: {ingest_result}")

    per_symbol, all_dates = we.load_ledger(sheet)
    if not all_dates:
        print("No price history in RawDailyPrices yet -- nothing to do.")
        return
    latest_date = all_dates[-1]
    print(f"[2/6] Ledger loaded: {len(all_dates)} trading days, latest = {latest_date}, "
          f"{len(per_symbol)} tickers")

    # Monthly dedup needs every row ever entered (active + closed), so read
    # active_trades_weekly directly here, BEFORE fill_pending adds today's
    # new rows to it.
    all_records_for_dedup = read_records(sheet, "active_trades_weekly", we.ACTIVE_HEADER)

    last_scanned = we._get_state(sheet)
    scan_result = we.scan_new_candidates(sheet, per_symbol, all_dates, last_scanned, all_records_for_dedup)
    we._set_state(sheet, latest_date)
    print(f"[3/6] Scanned for new v1_45stc/v2_allstc signals since {last_scanned or '(first run)'}: "
          f"{scan_result}")

    fill_result = we.fill_pending(sheet, per_symbol, all_dates)
    print(f"[4/6] Filled pending signals: {fill_result['filled']} "
          f"({fill_result['still_pending']} still waiting on next week's data)")
    for entry in fill_result["log"]:
        print(f"       {entry['action']}: {entry['ticker']} ({entry['model']}) "
              f"@ {entry['price']} on {entry['date']}")

    records = we.evaluate_active(sheet, per_symbol, all_dates)
    print(f"[5/6] Evaluated open positions: "
          f"{sum(1 for r in records if r['status']=='ACTIVE')} still in Hold, "
          f"{sum(1 for r in records if r['status']!='ACTIVE')} closed (lifetime total)")

    we.update_views(sheet, records, newly_filled=fill_result["log"])

    preview = we.preview_today(sheet, per_symbol, all_dates)
    print(f"[6/6] PREVIEW (informational only, as of {preview['as_of']}): "
          f"{len(preview['candidates'])} ticker(s) currently passing v1_45stc/v2_allstc's "
          f"screen (see 'Preview' tab) -- NOT queued, purely a look-ahead.")
    for c in preview["candidates"][:15]:
        print(f"       {c['ticker']} ({c['model']}): rsi={c['rsi']}")


if __name__ == "__main__":
    main()
