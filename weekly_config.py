"""
Central configuration for the COMBINED v1_45stc + v2_allstc model --
REPLACES the old Branch A/B regime-switching model entirely (that model,
its config keys, and its TABS entries under weekly_engine.py are gone;
this is a from-scratch strategy, not a tweak of the old one).

v1_45stc: FIXED 45-stock universe. Signal = RSI(14) between 10-40 AND
          today's close is >= 25% below its own 30-day rolling high AND
          20-day turnover >= MIN_TURNOVER_20D.
v2_allstc: BROAD DSE universe (every ticker in the ledger EXCEPT the 4
          index rows, treasury bonds, corporate bonds/sukuk, closed-end
          mutual funds, minus 2 explicitly protected names -- see
          V2_PROTECTED_SYMBOLS -- and dynamically excluding any stock
          whose CLOSE that day is below V2_MIN_PRICE). Signal = RSI(14)
          between 10-30 AND close has dropped >= 35% over the last 10
          trading days AND 20-day turnover >= MIN_TURNOVER_20D.

Both legs share the SAME exit rule: single entry at the NEXT trading
day's OPEN after the signal, 35% target / 45% stop (checked against
each day's HIGH/LOW, exactly like the backtest -- NOT a closing-price
day-count ladder like the old Branch A/B model used), hard time-exit at
120 trading days (that day's close). No averaging-down -- that was a
Branch-A-only mechanic that doesn't exist in this model; a symbol CAN
have more than one concurrent open position, capped only by the
combined monthly-entry rule below.

Cross-model dedup: v1_45stc + v2_allstc entries are capped at
MAX_COMBINED_ENTRIES_PER_MONTH per (symbol, calendar month) TOTAL
(counting closed AND still-open positions, plus anything still queued in
PendingWeekly) -- v1_45stc wins ties on the same (date, symbol).

This matches combined_v1_45stc_v2_allstc_final.py exactly, adapted only
for weekly-cadence LIVE signal generation (screens every new trading day
in a week's paste, not a one-shot backtest loop) instead of a backtest.
"""
import re

RSI_PERIOD = 14
MIN_TURNOVER_20D = 500_000
MAX_COMBINED_ENTRIES_PER_MONTH = 2
PRIORITY_MODEL = "v1_45stc"

# ==========================================================================
# ---- v1_45stc ----
# ==========================================================================
V1_TARGET_PCT = 0.35
V1_STOP_PCT = 0.45
V1_MAX_HOLD_DAYS = 120
V1_HIGH_LOOKBACK_DAYS = 30
V1_BELOW_HIGH_MIN_PCT = 0.25
V1_RSI_LOW, V1_RSI_HIGH = 10, 40

V1_UNIVERSE = [
    "ACMELAB", "APEXFOOT", "ARGONDENIM", "BANKASIA", "BATBC", "BERGERPBL", "BRACBANK",
    "BSRMLTD", "BSRMSTEEL", "BXPHARMA", "CITYBANK", "DBH", "DHAKABANK", "DUTCHBANGL",
    "EBL", "EHL", "ENVOYTEX", "ESQUIRENIT", "GP", "HWAWELLTEX", "IDLC", "JAMUNABANK",
    "JAMUNAOIL", "LHB", "MARICO", "MATINSPINN", "MPETROLEUM", "MTB", "NCCBANK",
    "PADMAOIL", "PRIMEBANK", "PUBALIBANK", "ROBI", "SAIHAMCOT", "SAIHAMTEX",
    "SHAHJABANK", "SIMTEX", "SOUTHEASTB", "SQUARETEXT", "SQURPHARMA", "SUMITPOWER",
    "TRUSTBANK", "UPGDCL", "UTTARABANK", "WALTONHIL",
]  # 45 symbols

# ==========================================================================
# ---- v2_allstc ----
# ==========================================================================
V2_TARGET_PCT = 0.35
V2_STOP_PCT = 0.45
V2_MAX_HOLD_DAYS = 120
V2_DROP_LOOKBACK_DAYS = 10
V2_DROP_MIN_PCT = 0.35
V2_RSI_LOW, V2_RSI_HIGH = 10, 30
V2_MIN_PRICE = 5.0  # dynamic: checked every day per-ticker, not a static exclusion list

V2_INDEX_SYMBOLS = {"00DS30", "00DSES", "00DSEX", "00DSMEX"}

# Bangladesh Govt Treasury Bonds -- symbol pattern TB<tenor>Y<MMYY>, e.g. TB5Y0125.
# Matched by regex, not hardcoded, since new bonds get listed periodically.
V2_TREASURY_BOND_PATTERN = re.compile(r"^TB\d+Y")

# Corporate perpetual bonds / sukuk (explicit list, 9 symbols)
V2_CORP_BOND_SUKUK_SYMBOLS = {
    "ABBLPBOND", "APSCLBOND", "BANKASI1PB", "BEXGSUKUK",
    "CBLPBOND", "DBLPBOND", "MBPLCPBOND", "SEB1PBOND", "UCB2PBOND",
}  # 9

# Closed-end mutual funds. NOTE: 37 entries here -- one more than the "36"
# originally specified. The 6 flagged below (newer SEML/VAML/CAPM AMC
# growth/balanced/shariah/fixed-income naming) are the group most likely
# to contain the extra one -- spot-check and trim if 36 is authoritative.
V2_MUTUAL_FUND_SYMBOLS = {
    "1JANATAMF", "1STPRIMFMF", "ABB1STMF", "AIBL1STIMF", "CAPMBDBLMF", "CAPMIBBLMF",
    "DBH1STMF", "EBL1STMF", "EBLNRBMF", "EXIM1STMF", "GLDNJMF", "GRAMEENS2",
    "GREENDELMF", "ICB3RDNRB", "ICBAGRANI1", "ICBAMCL2ND", "ICBEPMF1S1", "ICBSONALI1",
    "IFIC1STMF", "IFILISLMF1", "LRGLOBMF1", "MBL1STMF", "NCCBLMF1", "PF1STMF",
    "PHPMF1", "POPULAR1MF", "PRIME1ICBA", "SEMLLECMF", "TRUSTB1MF", "VAMLBDMF1",
    "RELIANCE1",  # verified: "Reliance One", 1st scheme of Reliance Insurance Mutual Fund
    "ATCSLGF", "CAPITECGBF", "FBFIF", "SEMLFBSLGF", "SEMLIBBLSF", "VAMLRBBF",
    # ^ these 6 are the "extra symbol" candidates -- confirm/trim to 36 if needed.
}  # 37

# Explicitly protected: NEVER excluded even though a naive name-pattern
# filter would sweep them up.
V2_PROTECTED_SYMBOLS = {"ICB", "AMCL(PRAN)"}

# Informational only (both legs' feature builders are NaN-safe via
# pandas rolling/pct_change min_periods, so a day with too little history
# naturally fails its signal condition rather than needing an explicit
# gate) -- kept here for logging / inspect_ticker.py's warnings.
MIN_BARS_REQUIRED = max(V1_HIGH_LOOKBACK_DAYS + RSI_PERIOD, max(V2_DROP_LOOKBACK_DAYS, RSI_PERIOD)) + 2
