"""
CLI tool to peek at a ticker's internal state and scores today.
Updated for v2 (composite /20 score, independent T1/T2/T3 setups).
"""
import sys
import os

# Adjust path so we can import from the parent directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sheet_data_source import get_historical_data
from indicators import compute_all
from scoring import score_stock
from risk_manager import build_setup
from sheets_manager import open_sheet
from config import MIN_BARS_REQUIRED

def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/inspect_ticker.py <TICKER>")
        sys.exit(1)
        
    ticker = sys.argv[1].upper()
    sheet = open_sheet()
    
    print(f"Fetching historical data for {ticker}...")
    hist = get_historical_data(sheet, ticker)
    
    if hist.empty:
        print("Error: No data found for this ticker in RawDailyPrices.")
        return
    if len(hist) < MIN_BARS_REQUIRED:
        print(f"Error: Only {len(hist)} bars found. Needs >= {MIN_BARS_REQUIRED}.")
        return

    # Process indicators and scores
    enriched = compute_all(hist)
    technical = score_stock(enriched)
    setup = build_setup(ticker, hist, technical)

    # Print breakdown
    print(f"\n--- {ticker} Technical Breakdown ({technical['technical_total']}/18) ---")
    for key, value in technical["breakdown"].items():
        print(f"  {key}: {value} pts")

    print(f"\n--- Final Setup Formulation ({setup['score']}/20) ---")
    print(f"  Valid for Trading: {'Yes' if setup['valid'] else 'No'}")
    print(f"  Entry Band: {setup['entry_low']} to {setup['entry_high']}")
    print(f"  Stop Loss: {setup['stop_loss']} (Source: {setup['sl_source']}, Bonus: {setup['sl_quality']} pt)")
    print(f"  Risk Per Share (R): {setup['risk_per_share']}")
    
    print("\n--- Independent Targets ---")
    print(f"  Target 1 (1.0R): {setup['target_1']}")
    print(f"  Target 2 (1.5R): {setup['target_2']}")
    print(f"  Target 3 (2.0R): {setup['target_3']}")
    print(f"  Target Bonus: {setup['target_quality']} pt (Source: {setup['target_source']})")

if __name__ == "__main__":
    main()
