"""
Run with: python tests/test_sheet_data_source.py

Tests parse_staging_rows() — the function that turns a raw paste from
DSE's site into clean ledger rows — against realistic messy input
(commas in big numbers, blank rows, dashes for missing data, a header
using DSE's actual naming like "LTP*"/"CLOSEP*"). Pure function, no
network or Google Sheets needed.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sheet_data_source import parse_staging_rows


def main():
    pasted = [
        ["TRADING CODE", "LTP*", "HIGH", "LOW", "CLOSEP*", "YCP", "TRADE", "VOLUME"],
        ["ACI", "203.3", "205.0", "198.5", "203.3", "198.2", "412", "69,219"],
        ["BEXIMCO", "28.2", "28.9", "27.1", "28.2", "27.7", "3021", "7,503,379"],
        ["", "", "", "", "", "", "", ""],           # blank row — should be skipped
        ["BROKENROW", "-", "-", "-", "-", "-", "-", "-"],  # no real numbers — should be skipped
        ["GP", "256.7", "260.0", "253.1", "256.7", "259.4", "210", "272,399"],
    ]

    clean_rows, skipped = parse_staging_rows(pasted, "2026-07-12")
    print("Clean rows:")
    for r in clean_rows:
        print(" ", r)
    print("Skipped:", skipped)

    assert len(clean_rows) == 3, f"expected 3 clean rows, got {len(clean_rows)}"
    assert skipped == 2, f"expected 2 skipped rows, got {skipped}"
    assert clean_rows[0] == ["2026-07-12", "ACI", 205.0, 198.5, 203.3, 69219.0]
    assert clean_rows[1] == ["2026-07-12", "BEXIMCO", 28.9, 27.1, 28.2, 7503379.0]
    assert clean_rows[2] == ["2026-07-12", "GP", 260.0, 253.1, 256.7, 272399.0]

    # Empty / near-empty paste should return cleanly, not crash.
    empty_clean, empty_skipped = parse_staging_rows([], "2026-07-12")
    assert empty_clean == [] and empty_skipped == 0

    header_only_clean, _ = parse_staging_rows([pasted[0]], "2026-07-12")
    assert header_only_clean == []

    print("\nALL SHEET DATA SOURCE TESTS PASSED.")


if __name__ == "__main__":
    main()
