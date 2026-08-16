"""
Config for the COMBINED regime-switching weekly model (branch_a_model.py
+ branch_b_uptrend_model.py, unified via combined_regime_model.py), which
REPLACES the earlier Branch-A-only weekly pipeline, the old daily model,
and the Model F weekly model in production.

One regime switch (Thursday-close, causal), two dedicated branches:
  idx_ret10 >= REGIME_UP_THRESHOLD  -> UPTREND     -> Branch B fires
  idx_ret10 <  REGIME_UP_THRESHOLD  -> NOT-UPTREND  -> Branch A fires
Exactly one branch is eligible per week, by construction (see
weekly_engine.scan_new_candidates).
"""

INDEX_SYMBOL = "00DSEX"

# ---- Regime gate (shared) ----
REGIME_LOOKBACK_DAYS = 10
REGIME_UP_THRESHOLD = 0.015

MAX_TRADES_PER_WEEK = 1     # single top-ranked candidate per Thursday, across all tickers
MIN_BARS_REQUIRED = 21
TICK_DECIMALS = 1

# ---- Branch A params (Sideways/Downtrend dip-buy) ----
RSI_PERIOD = 14
RSI_MIN, RSI_MAX = 10, 30
LOOKBACK_LOW_DAYS = 60
PROXIMITY_TO_LOW_MAX_PCT = 8
MIN_TURNOVER_20D = 3_000_000
MIN_VOL20_PCT = 1.2
RELSTRENGTH_LOOKBACK_DAYS = 20
RS_ELIGIBILITY_MAX = -0.05

# Branch A averaging-down: confirmed band, one average-down per position,
# only after day 10, only while unrealized return is between these two.
AVERAGING_ENABLED = True
AVERAGE_MIN_DAY = 10
AVERAGE_BAND_LO = -20.0
AVERAGE_BAND_HI = -15.0

# ---- Branch B params (Uptrend breakout -- grid-search winner, Aug 16 2026) ----
# No averaging-down for Branch B (not validated for this branch).
B_RSI_PERIOD = 14
B_RSI_LO, B_RSI_HI = 55, 70
B_MIN_VOL20_FRAC = 0.001
B_VOL_MULT = 1.5

TICKERS = [
    "BBS", "CROWNCEMNT", "ESQUIRENIT", "UNITEDINS", "DSSL", "LINDEBD", "MHSML",
    "BDLAMPS", "ECABLES", "QUEENSOUTH", "SINOBANGLA", "BPPL", "VFSTDL", "BDTHAI",
    "NAVANAPHAR", "AMANFEED", "EASTLAND", "SPCL", "SANDHANINS", "NAHEEACP",
    "DHAKAINS", "SHEPHERD", "NFML", "BXPHARMA", "PUBALIBANK", "CVOPRL",
    "RAKCERAMIC", "SICL", "ICBAGRANI1", "MEGHNALIFE", "NCCBANK", "ICB3RDNRB",
    "JAMUNABANK", "ICBSONALI1", "IBP", "NITOLINS", "BSCPLC", "PRAGATIINS",
    "GENEXIL", "SIMTEX", "JHRML", "PURABIGEN", "TITASGAS", "SHASHADNIM", "EBL",
    "REPUBLIC", "MIRAKHTER", "GHAIL", "SALAMCRST", "QUASEMIND", "POPULARLIF",
    "SAPORTL", "SEAPEARL", "COPPERTECH", "ACFL", "DAFODILCOM", "DGIC", "ASIAINS",
    "PRIME1ICBA", "AOL", "ENVOYTEX", "STANDARINS", "DELTALIFE", "MIDLANDBNK",
    "EASTERNINS", "GOLDENSON", "ROBI", "SOUTHEASTB", "APEXTANRY", "FINEFOODS",
    "EHL", "PRIMELIFE", "RUPALILIFE", "BGIC", "SQUARETEXT", "NORTHRNINS", "DBH",
    "UTTARABANK", "ACMEPL", "RUPALIINS", "INDEXAGRO", "RAHIMTEXT", "JMISMDL",
    "CLICL", "ARGONDENIM", "SAIHAMTEX", "AGNISYSL", "PTL", "AL-HAJTEX",
    "BDAUTOCA", "ADNTEL", "EPGL", "ICB", "BSRMLTD", "PENINSULA", "ALARABANK",
    "MONNOCERA", "GLOBALINS", "RELIANCE1", "SAMATALETH", "UNIONINS",
    "FEDERALINS", "ISNLTD", "RUNNERAUTO", "SONALILIFE", "DSHGARME", "KAY&QUE",
    "SONARGAON", "HWAWELLTEX", "FEKDIL", "SILVAPHL", "PRIMEBANK", "IFADAUTOS",
    "BANKASIA", "CITYBANK", "AMBEEPHA", "ITC", "AGRANINS", "BDCOM", "ORIONINFU",
    "SHARPIND", "APEXFOOT", "BSC", "BATASHOE", "NPOLYMER", "DOREENPWR",
    "CENTRALINS", "SAIHAMCOT", "WATACHEM", "KDSALTD", "TILIL", "ACI", "MTB",
    "RANFOUNDRY", "GQBALLPEN", "ISLAMIINS", "CONTININS", "PIONEERINS",
    "GPHISPAT", "CONFIDCEM", "BEACONPHAR", "IBNSINA", "SONALIPAPR", "LANKABAFIN",
    "ARAMIT", "KOHINOOR", "KBPPWBIL", "SHAHJABANK", "BATBC", "SEMLIBBLSF",
    "WALTONHIL", "OLYMPIC", "GREENDELT", "JAMUNAOIL", "EASTRNLUB", "MATINSPINN",
    "RENATA", "ACMELAB", "TAMIJTEX", "APEXSPINN", "SAMORITA", "PADMAOIL",
    "PRIMEINSUR", "PARAMOUNT", "UNITEDFIN", "TOSRIFA", "PHENIXINS", "VAMLRBBF",
    "MONNOAGML", "MONNOFABR", "ACIFORMULA", "SQURPHARMA", "NTLTUBES",
    "MALEKSPIN", "AMCL(PRAN)", "MJLBD",
]
