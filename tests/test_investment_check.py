"""
Run with: python tests/test_investment_check.py

Tests check_ticker()'s three-condition logic against engineered synthetic
data — a clear long downtrend near its own historical low (should match)
and a clear uptrend (should not) — plus the dynamic MA period behavior
with a short history, and that main() correctly writes matches into the
Investment tab. No network or real Google Sheets needed (a fake worksheet
stands in for the Sheets API).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from datetime import date, timedelta


class FakeWorksheet:
    def __init__(self, rows=None):
        self.rows = rows or []

    def get_all_values(self):
        return self.rows

    def append_row(self, row):
        self.rows.append(row)

    def append_rows(self, rows, value_input_option=None):
        self.rows.extend(rows)

    def clear(self):
        self.rows = []


class FakeSheet:
    def __init__(self, tabs):
        self._tabs = tabs

    def worksheet(self, title):
        import gspread
        if title not in self._tabs:
            raise gspread.WorksheetNotFound(title)
        return self._tabs[title]

    def add_worksheet(self, title, rows, cols):
        ws = FakeWorksheet()
        self._tabs[title] = ws
        return ws


def build_rows(ticker: str, n: int, start_price: float, drift: float, seed: int):
    rng = np.random.default_rng(seed)
    rows = []
    price = start_price
    for i in range(n):
        d = (date(2026, 7, 15) - timedelta(days=n - i)).isoformat()
        price *= (1 + rng.normal(drift, 0.01))
        rows.append([d, ticker, round(price * 1.008, 2), round(price * 0.992, 2), round(price, 2), 50000])
    return rows


def main():
    header = ["date", "ticker", "high", "low", "close", "volume"]
    rows = [header]
    rows += build_rows("DOWNBEAT", 120, 100.0, -0.004, seed=11)   # grinds down near its own low
    rows += build_rows("HEALTHY", 120, 100.0, 0.004, seed=11)     # grinds up, away from any low
    rows += build_rows("SHORTHIST", 50, 100.0, -0.001, seed=5)    # only 50 days — tests dynamic MA

    fake_sheet = FakeSheet({"RawDailyPrices": FakeWorksheet(rows)})

    import sheet_data_source
    sheet_data_source._price_ledger_cache = None  # reset cache for a clean test run

    from scripts.investment_check import check_ticker

    r_down = check_ticker(fake_sheet, "DOWNBEAT")
    r_healthy = check_ticker(fake_sheet, "HEALTHY")
    r_short = check_ticker(fake_sheet, "SHORTHIST")
    r_missing = check_ticker(fake_sheet, "NOTINLEDGER")

    print("DOWNBEAT  :", r_down)
    print("HEALTHY   :", r_healthy)
    print("SHORTHIST :", r_short)
    print("MISSING   :", r_missing)

    assert r_down is not None, "a stock grinding down near its own low should match"
    assert r_healthy is None, "a stock in a clean uptrend should not match"
    assert r_missing is None, "a ticker with no rows at all must not crash — just no match"
    assert r_short is not None, "SHORTHIST should still match despite < 200 days of history"
    assert r_short["ma_period"] == 50, f"MA period should dynamically be 50, got {r_short['ma_period']}"

    print("\n--- Full main() flow: confirm Investment tab gets written correctly ---")
    import scripts.investment_check as inv
    inv.open_sheet = lambda: fake_sheet  # investment_check imported open_sheet by name, patch here
    sheet_data_source._price_ledger_cache = None
    inv.INVESTMENT_WATCHLIST = ["DOWNBEAT", "HEALTHY", "SHORTHIST", "NOTINLEDGER"]
    inv.main()

    written = fake_sheet._tabs["Investment"].rows
    print("Investment tab contents:", written)
    assert written[0] == inv.INVESTMENT_HEADER
    written_tickers = {row[0] for row in written[1:]}
    assert written_tickers == {"DOWNBEAT", "SHORTHIST"}, \
        f"expected only DOWNBEAT and SHORTHIST written, got {written_tickers}"
    assert "HEALTHY" not in written_tickers
    assert "NOTINLEDGER" not in written_tickers

    print("\nALL INVESTMENT CHECK TESTS PASSED.")


if __name__ == "__main__":
    main()
