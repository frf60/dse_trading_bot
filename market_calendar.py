"""
Guards against running on DSE holidays. GitHub Actions cron can only filter
by weekday (Sun-Thu are DSE trading days, encoded in the workflow file) —
it can't know about Eid, other government holidays, or ad-hoc closures.
Maintain those in holidays.txt (one ISO date per line, '#' for comments).
"""
import os
from datetime import date
from config import HOLIDAY_FILE


def is_market_holiday(today: str = None) -> bool:
    today = today or date.today().isoformat()
    if not os.path.exists(HOLIDAY_FILE):
        return False
    with open(HOLIDAY_FILE) as f:
        holidays = {line.strip() for line in f if line.strip() and not line.startswith("#")}
    return today in holidays
