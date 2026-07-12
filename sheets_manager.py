"""
Thin wrapper around gspread. All Sheets I/O goes through here so the rest
of the pipeline never touches the API directly.

One-time setup:
  1. Google Cloud Console -> new project -> enable "Google Sheets API".
  2. Create a Service Account -> Keys -> Add key -> JSON. Download it.
  3. Open the JSON, copy the "client_email" value, and share your target
     Google Sheet with that email as Editor.
  4. In GitHub: repo Settings -> Secrets and variables -> Actions ->
     New repository secret, named GOOGLE_SERVICE_ACCOUNT_JSON, value =
     the full contents of the JSON key file.
  5. Put the Sheet's ID (from its URL) into config.SPREADSHEET_ID.
"""
import os
import json
import gspread
from google.oauth2.service_account import Credentials
from config import SPREADSHEET_NAME, SPREADSHEET_ID, TABS

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _client():
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise RuntimeError(
            "GOOGLE_SERVICE_ACCOUNT_JSON env var not set. Locally, export the contents "
            "of your service-account key file into that variable; in CI, set it as a secret."
        )
    creds = Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)
    return gspread.authorize(creds)


def open_sheet():
    gc = _client()
    return gc.open_by_key(SPREADSHEET_ID) if SPREADSHEET_ID else gc.open(SPREADSHEET_NAME)


def get_tab(sheet, tab_key: str, header: list):
    """Fetch a worksheet by its config key, creating it with a header row if it doesn't exist."""
    title = TABS[tab_key]
    try:
        ws = sheet.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = sheet.add_worksheet(title=title, rows=1000, cols=len(header) + 2)
        ws.append_row(header)
    return ws


def read_records(sheet, tab_key: str, header: list) -> list:
    ws = get_tab(sheet, tab_key, header)
    return ws.get_all_records()


def overwrite_tab(sheet, tab_key: str, header: list, rows: list):
    """Clears a tab and rewrites it — used for the Buy/Hold/Sell snapshot views each run."""
    ws = get_tab(sheet, tab_key, header)
    ws.clear()
    ws.append_row(header)
    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")


def append_rows(sheet, tab_key: str, header: list, rows: list):
    ws = get_tab(sheet, tab_key, header)
    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
