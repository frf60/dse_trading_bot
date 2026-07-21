"""
Barebones backtester over local CSV data.
Updated for v2 (single composite score, T1/T2/T3 independent tracking).
"""
import pandas as pd
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indicators import compute_all
from scoring import score_stock
from risk_manager import build_setup
from config import MIN_BARS_REQUIRED, MIN_SCORE

def run_backtest(csv_path="data/amarstock_prices_2026-07-12.csv", target_ticker="PUBALIBANK"):
    if not os.path.exists(csv_path):
        print(f"Cannot find data file at {csv_path}")
        return

    df = pd.read_csv(csv_path)
    
    # Filter and format standard Amarstock CSV columns
    df = df[df["TradingCode"] == target_ticker].sort_values("Date").reset_index(drop=True)
    df.columns = [c.lower() for c in df.columns]

    if len(df) < MIN_BARS_REQUIRED:
        print(f"Not enough data for {target_ticker}.")
        return

    active_trade = None
    trades_log = []

    print(f"Running simulation for {target_ticker}...")

    # Iterate through history simulating daily EOD reads
    for i in range(MIN_BARS_REQUIRED, len(df)):
        hist_slice = df.iloc[:i].copy()
        live_today = df.iloc[i] 

        if active_trade:
            # Active Position Evaluation (Mimicking state_manager.py)
            sl = active_trade["stop_loss"]
            live_low = live_today["low"]
            live_high = live_today["high"]

            # 1. Stop Loss Evaluation (Hits all ACTIVE targets)
            if live_low <= sl:
                for k in ["target_1", "target_2", "target_3"]:
                    if active_trade[f"{k}_status"] == "ACTIVE":
                        active_trade[f"{k}_status"] = "SL_HIT"
                active_trade["status"] = "CLOSED"
                trades_log.append(active_trade)
                active_trade = None
                continue

            # 2. Independent Target Evaluation
            for k in ["target_1", "target_2", "target_3"]:
                if active_trade[f"{k}_status"] == "ACTIVE" and live_high >= active_trade[k]:
                    active_trade[f"{k}_status"] = "TARGET_HIT"

            # 3. Check if all targets are resolved
            if all(active_trade[f"{k}_status"] != "ACTIVE" for k in ["target_1", "target_2", "target_3"]):
                active_trade["status"] = "CLOSED"
                trades_log.append(active_trade)
                active_trade = None
        else:
            # Look for a new setup
            enriched = compute_all(hist_slice)
            try:
                tech_score = score_stock(enriched)
                setup = build_setup(target_ticker, hist_slice, tech_score)
                
                if setup["valid"] and setup["score"] >= MIN_SCORE:
                    active_trade = setup
                    active_trade["entry_date"] = live_today["date"]
                    for k in ["target_1", "target_2", "target_3"]:
                        active_trade[f"{k}_status"] = "ACTIVE"
                    active_trade["status"] = "ACTIVE"
            except Exception:
                pass

    print(f"\nBacktest complete for {target_ticker}. Total fully resolved trades: {len(trades_log)}")
    print("-" * 75)
    for t in trades_log:
        print(f"Entry: {t['entry_date']} | SL: {t['sl_source']} | T1: {t['target_1_status']} | T2: {t['target_2_status']} | T3: {t['target_3_status']}")
    print("-" * 75)

if __name__ == "__main__":
    # Feel free to change target_ticker via arguments if needed
    ticker = sys.argv[1] if len(sys.argv) > 1 else "PUBALIBANK"
    run_backtest(target_ticker=ticker)
