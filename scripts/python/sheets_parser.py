"""
sheets_parser.py — Fetches and parses the P&L Google Sheet into clean dicts.

Column layout (Sheet1):
  Spalte 1 (date) | Revenue | COG | Adspend Google | Mediabuying | EMPLOYEE |
  Transaction fee | Profit | ROAS | Profit% | COG% | CVR% | CPC | Refunds | Refund%
"""

import re
import logging
from datetime import datetime, date
from typing import Optional

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import config

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

# Maps raw sheet header text → canonical internal name
COLUMN_MAP = {
    "spalte 1":       "report_date",
    "date":           "report_date",
    "revenue":        "revenue",
    "cog":            "cog",
    "adspend google": "adspend_google",
    "mediabuying":    "mediabuying",
    "employee":       "employee_cost",
    "transaction fee":"transaction_fee",
    "profit":         "profit",
    "roas":           "roas",
    "profit%":        "profit_pct",
    "cog%":           "cog_pct",
    "cvr%":           "cvr_pct",
    "cpc":            "cpc",
    "refunds":        "refunds",
    "refund%":        "refund_pct",
}

# All known date formats in the sheet
DATE_FORMATS = [
    "%Y-%m-%d",
    "%d.%m.%Y",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d-%m-%Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%d %b %Y",
]


def _build_service():
    creds = Credentials.from_service_account_file(
        config.GOOGLE_SERVICE_ACCOUNT_JSON,
        scopes=SCOPES,
    )
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _parse_date(raw: str) -> Optional[date]:
    raw = raw.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    logger.warning("Could not parse date: %r", raw)
    return None


def _to_float(raw) -> Optional[float]:
    if raw is None or str(raw).strip() == "":
        return None
    cleaned = re.sub(r"[%,$€£\s]", "", str(raw))
    try:
        return float(cleaned)
    except ValueError:
        return None


def _map_headers(header_row: list) -> dict:
    """Return {col_index: canonical_name} for the columns we care about."""
    mapping = {}
    for idx, cell in enumerate(header_row):
        normalised = str(cell).strip().lower()
        canonical = COLUMN_MAP.get(normalised)
        if canonical:
            mapping[idx] = canonical
    return mapping


def fetch_pl_data() -> list[dict]:
    """
    Authenticate with Google Sheets and return a list of dicts — one per
    data row — with column names matching the daily_pl schema.

    Always re-fetches the full sheet; the caller decides how much to upsert.
    """
    logger.info("Fetching P&L data from Google Sheets (sheet_id=%s)", config.GOOGLE_SHEET_ID)

    try:
        service = _build_service()
        sheet_range = f"{config.SHEET_TAB_NAME}!A1:Z2000"
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=config.GOOGLE_SHEET_ID, range=sheet_range)
            .execute()
        )
    except HttpError as exc:
        logger.error("Google Sheets API error: %s", exc)
        raise

    raw_rows = result.get("values", [])
    if not raw_rows:
        logger.warning("Sheet returned no data.")
        return []

    # First non-empty row is the header
    header_row = raw_rows[0]
    col_map = _map_headers(header_row)

    if "report_date" not in col_map.values():
        raise ValueError(
            "Could not find a date column in the sheet headers. "
            f"Headers found: {header_row}"
        )

    date_col_idx = next(i for i, name in col_map.items() if name == "report_date")

    rows_out = []
    skipped = 0

    for row_num, raw_row in enumerate(raw_rows[1:], start=2):
        # Skip completely empty rows
        if not any(str(c).strip() for c in raw_row):
            skipped += 1
            continue

        # Skip rows where the date cell is blank or looks like another header
        date_raw = raw_row[date_col_idx] if date_col_idx < len(raw_row) else ""
        if not str(date_raw).strip():
            skipped += 1
            continue

        parsed_date = _parse_date(str(date_raw))
        if parsed_date is None:
            logger.debug("Row %d: skipping unparseable date %r", row_num, date_raw)
            skipped += 1
            continue

        record: dict = {"report_date": parsed_date}

        for col_idx, canonical in col_map.items():
            if canonical == "report_date":
                continue
            raw_val = raw_row[col_idx] if col_idx < len(raw_row) else None
            record[canonical] = _to_float(raw_val)

        rows_out.append(record)

    logger.info(
        "Parsed %d data rows from sheet (%d rows skipped).",
        len(rows_out), skipped,
    )
    return rows_out
