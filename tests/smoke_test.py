"""
Quick sanity check to ensure the math pipelines run without crashing.
Updated for v2 (single composite score /20, T1/T2/T3 independent tracking).
"""
import pandas as pd
import numpy as np
from indicators import compute_all
from scoring import score_stock
from risk_manager import build_setup
from config import SCORE_MAX

def test_pipeline():
    # Mock 100 days of price and volume data
    np.random.seed(42)
    prices = np.linspace(100, 150, 100) + np.random.normal(0, 2, 100)
    df = pd.DataFrame({
        "high": prices + 2.5,
        "low": prices - 2.5,
        "close": prices,
        "volume": np.random.randint(1000, 15000, 100)
    })

    # 1. Test indicators
    enriched = compute_all(df)
    assert "rsi_14d" in enriched.columns
    assert "macd_hist" in enriched.columns

    # 2. Test scoring (Technical only, max 18)
    technical_score = score_stock(enriched)
    assert "technical_total" in technical_score
    assert technical_score["technical_total"] <= 18
    assert "breakdown" in technical_score

    # 3. Test setup builder (Adds SL/Target bonus, max 20)
    setup = build_setup("TEST_TICKER", df, technical_score)
    assert "score" in setup
    assert setup["score"] <= SCORE_MAX
    assert "target_1" in setup
    assert "target_2" in setup
    assert "target_3" in setup
    
    # Ensure targets are properly scaled sequentially
    assert setup["target_1"] < setup["target_2"] < setup["target_3"]
    assert setup["stop_loss"] < setup["entry_high"]
    
    print("Smoke test passed: The new v2 pipeline generated a valid composite setup.")

if __name__ == "__main__":
    test_pipeline()
