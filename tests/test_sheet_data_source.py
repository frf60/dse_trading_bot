"""
Run with: python tests/test_sheet_data_source.py

Tests parse_staging_rows() — the function that turns a raw weekly paste
(RawStaging: Date, Scrip, Open, High, Low, Close, Volume — Sun-Thu, every
ticker, one paste per Friday run) into clean RawDailyPrices rows —
against realistic messy input (commas in big numbers, blank rows, dashes
for missing data, a header using DSE's actual naming like "LTP*"/
"CLOSEP*"/"TRADING CODE", and a Date column in a non-ISO format). Pure
function, no network or Google Sheets needed.

Rewritten for the per-row-Date fix: the old version of this test pasted
rows with NO Date column at all and asserted a 6-field row (no "open")
-- that matched neither the current RAW_HEADER (7 fields, "open"
included) nor the weekly pipeline's actual paste shape (one paste covers
5 different trading days, so every row needs its OWN date, not a single
run_date stamped on all of them). This version pastes THREE different
dates in one go, the way a real Friday paste would, and checks each
clean row keeps its own date.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sheet_data_source import parse_staging_rows


def main():
    pasted = [
        ["DATE", "TRADING CODE", "OPENP*", "LTP*", "HIGH", "LOW", "CLOSEP*", "YCP", "TRADE", "VOLUME"],
        ["12-Jul-2026", "ACI", "199.0", "203.3", "205.0", "198.5", "203.3", "198.2", "412", "69,219"],
        ["12-Jul-2026", "BEXIMCO", "27.8", "28.2", "28.9", "27.1", "28.2", "27.7", "3021", "7,503,379"],
        ["", "", "", "", "", "", "", "", "", ""],           # blank row — should be skipped
        ["13-Jul-2026", "BROKENROW", "-", "-", "-", "-", "-", "-", "-", "-"],  # no real numbers — should be skipped
        ["13-Jul-2026", "GP", "255.0", "256.7", "260.0", "253.1", "256.7", "259.4", "210", "272,399"],
        ["16-Jul-2026", "ACI", "204.0", "206.5", "207.2", "203.0", "206.5", "203.3", "388", "51,004"],
    ]

    clean_rows, skipped = parse_staging_rows(pasted)
    print("Clean rows:")
    for r in clean_rows:
        print(" ", r)
    print("Skipped:", skipped)

    assert len(clean_rows) == 4, f"expected 4 clean rows, got {len(clean_rows)}"
    assert skipped == 2, f"expected 2 skipped rows, got {skipped}"

    # Each row keeps its OWN date (three distinct trading days here, not
    # one run_date stamped on everything) -- this is the actual bug fix.
    assert clean_rows[0] == ["2026-07-12", "ACI", 199.0, 205.0, 198.5, 203.3, 69219.0]
    assert clean_rows[1] == ["2026-07-12", "BEXIMCO", 27.8, 28.9, 27.1, 28.2, 7503379.0]
    assert clean_rows[2] == ["2026-07-13", "GP", 255.0, 260.0, 253.1, 256.7, 272399.0]
    assert clean_rows[3] == ["2026-07-16", "ACI", 204.0, 207.2, 203.0, 206.5, 51004.0]

    dates_seen = {r[0] for r in clean_rows}
    assert dates_seen == {"2026-07-12", "2026-07-13", "2026-07-16"}, \
        f"expected 3 distinct trading days preserved, got {dates_seen}"

    # Empty / near-empty paste should return cleanly, not crash.
    empty_clean, empty_skipped = parse_staging_rows([])
    assert empty_clean == [] and empty_skipped == 0

    header_only_clean, _ = parse_staging_rows([pasted[0]])
    assert header_only_clean == []

    # A row with a BLANK Date cell (Date column present, but that one row's
    # cell is empty) falls back to the run_date argument -- the header
    # still must contain a Date column at all, since that's how the
    # weekly paste is meant to work; this only covers a stray blank cell.
    fallback_pasted = [
        ["DATE", "TRADING CODE", "OPENP*", "HIGH", "LOW", "CLOSEP*", "VOLUME"],
        ["", "ACI", "199.0", "205.0", "198.5", "203.3", "69,219"],
    ]
    fallback_clean, fallback_skipped = parse_staging_rows(fallback_pasted, run_date="2026-07-12")
    assert fallback_skipped == 0
    assert fallback_clean == [["2026-07-12", "ACI", 199.0, 205.0, 198.5, 203.3, 69219.0]]

    # No Date column in the header at all -> loud failure, not a silent
    # guess (matches the same policy as a missing ticker/OHLCV column).
    no_date_header = [
        ["TRADING CODE", "OPENP*", "HIGH", "LOW", "CLOSEP*", "VOLUME"],
        ["ACI", "199.0", "205.0", "198.5", "203.3", "69,219"],
    ]
    try:
        parse_staging_rows(no_date_header, run_date="2026-07-12")
        raise AssertionError("expected RuntimeError for a header with no Date column")
    except RuntimeError:
        pass

    print("\nALL SHEET DATA SOURCE TESTS PASSED.")


if __name__ == "__main__":
    main()
