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
import json
import os
import gspread
from google.oauth2.service_account import Credentials

def _client():
    # সরাসরি google_key.json ফাইল থেকে রিড করবে
    key_path = "google_key.json"
    if os.path.exists(key_path):
        with open(key_path, 'r') as f:
            service_account_info = json.load(f)
        creds = Credentials.from_service_account_info(service_account_info)
        return gspread.authorize(creds)
    else:
        # ফাইল না পেলে এরর দিবে
        raise RuntimeError("google_key.json file not found in root directory!")


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
    """
    Deliberately NOT using gspread's get_all_records() — that trusts
    whatever text is literally in the sheet's row 1 as the dict keys. If a
    tab's header row ever ends up out of sync with this project's own
    `header` list (e.g. created before a column-naming change, or hand-
    edited), get_all_records() silently returns dicts keyed by the wrong
    names and every r["ticker"]-style lookup downstream breaks with a
    KeyError. Reading positionally and re-zipping against `header` here
    makes every caller correct regardless of what row 1 actually says —
    row 1 is only ever treated as "the row to skip", not as data.
    """
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
    """Clears a tab and rewrites it — used for the Buy/Hold/Sell snapshot views each run."""
    ws = get_tab(sheet, tab_key, header)
    ws.clear()
    ws.append_row(header)
    if rows:
        # RAW, not USER_ENTERED: our date strings ("2026-04-15") must be stored
        # literally. USER_ENTERED lets Sheets auto-detect and reformat anything
        # that looks like a date/number/formula according to the sheet's locale,
        # which can silently corrupt round-tripping (write "2026-04-15", read
        # back something pandas parses as a different or invalid date).
        ws.append_rows(rows, value_input_option="RAW")


def append_rows(sheet, tab_key: str, header: list, rows: list):
    ws = get_tab(sheet, tab_key, header)
    if rows:
        ws.append_rows(rows, value_input_option="RAW")


def append_rows_with_retry(sheet, tab_key: str, header: list, rows: list, max_retries: int = 5):
    """
    Same as append_rows, but retries with exponential backoff on 429s.
    Needed for large backfills (tens of thousands of rows, sent in chunks)
    where enough back-to-back write calls can trip Sheets API's per-minute
    write quota even though each individual call is legitimate.
    """
    import time
    for attempt in range(max_retries):
        try:
            append_rows(sheet, tab_key, header, rows)
            return
        except gspread.exceptions.APIError as e:
            is_rate_limit = "429" in str(e) or "Quota exceeded" in str(e)
            if is_rate_limit and attempt < max_retries - 1:
                wait = 2 ** attempt  # 1, 2, 4, 8, 16 seconds
                print(f"  Rate limited, waiting {wait}s before retry {attempt + 2}/{max_retries}...")
                time.sleep(wait)
            else:
                raise
