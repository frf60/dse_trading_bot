import os
import json
import gspread
from google.oauth2.service_account import Credentials
from config import SPREADSHEET_NAME, SPREADSHEET_ID, TABS

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _client():
    # 1. Check for local credentials.json first
    if os.path.exists("credentials.json"):
        creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
        return gspread.authorize(creds)
        
    # 2. Check for the environment variable (for CI / GitHub Actions)
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if raw:
        creds = Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)
        return gspread.authorize(creds)

    # 3. Raise an error if neither exists
    raise RuntimeError(
        "Neither credentials.json file nor GOOGLE_SERVICE_ACCOUNT_JSON env var found."
    )


def open_sheet():
    gc = _client()
    return gc.open_by_key(SPREADSHEET_ID) if SPREADSHEET_ID else gc.open(SPREADSHEET_NAME)


def get_tab(sheet, tab_key: str, header: list):
    title = TABS[tab_key]
    try:
        ws = sheet.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = sheet.add_worksheet(title=title, rows=1000, cols=len(header) + 2)
        ws.append_row(header)
    return ws


def read_records(sheet, tab_key: str, header: list) -> list:
    ws = get_tab(sheet, tab_key, header)
    values = ws.get_all_values()
    if len(values) < 2:
        return []
    n = len(header)
    records = []
    for row in values[1:]:
        padded = row[:n] + [""] * max(0, n - len(row))
        records.append(dict(zip(header, padded)))
    return records


def overwrite_tab(sheet, tab_key: str, header: list, rows: list):
    ws = get_tab(sheet, tab_key, header)
    ws.clear()
    ws.append_row(header)
    if rows:
        ws.append_rows(rows, value_input_option="RAW")


def append_rows(sheet, tab_key: str, header: list, rows: list):
    ws = get_tab(sheet, tab_key, header)
    if rows:
        ws.append_rows(rows, value_input_option="RAW")


def append_rows_with_retry(sheet, tab_key: str, header: list, rows: list, max_retries: int = 5):
    import time
    for attempt in range(max_retries):
        try:
            append_rows(sheet, tab_key, header, rows)
            return
        except gspread.exceptions.APIError as e:
            is_rate_limit = "429" in str(e) or "Quota exceeded" in str(e)
            if is_rate_limit and attempt < max_retries - 1:
                wait = 2 ** attempt
                print(f"  Rate limited, waiting {wait}s before retry {attempt + 2}/{max_retries}...")
                time.sleep(wait)
            else:
                raise
