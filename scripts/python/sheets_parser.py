"""
sheets_parser.py — Fetches P&L data via Google Apps Script web app URL.

The script URL is set in .env as GOOGLE_SCRIPT_URL.
The Apps Script must be deployed as a web app with "Anyone" access and
return the sheet contents as JSON — either:

  Option A — array of arrays (first row = headers):
    [["Date","Revenue","COG",...], ["01.01.2025",10000,3000,...], ...]

  Option B — array of objects:
    [{"date":"01.01.2025","revenue":10000,"cog":3000,...}, ...]

  Option C — wrapped in an envelope:
    {"data": [...rows...], "success": true}
    {"rows": [...rows...]}

All three formats are detected and handled automatically.
"""

import logging
import re
from datetime import datetime, date
from typing import Optional

import requests

import config

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30  # seconds

# Maps raw sheet header text → canonical internal name (case-insensitive)
COLUMN_MAP = {
    "spalte 1":       "report_date",
    "datum":          "report_date",
    "date":           "report_date",
    "revenue":        "revenue",
    "cog":            "cog",
    "adspend google": "adspend_google",
    "ad spend":       "adspend_google",
    "adspend":        "adspend_google",
    "mediabuying":    "mediabuying",
    "media buying":   "mediabuying",
    "employee":       "employee_cost",
    "employee cost":  "employee_cost",
    "transaction fee":"transaction_fee",
    "transaction":    "transaction_fee",
    "profit":         "profit",
    "roas":           "roas",
    "profit%":        "profit_pct",
    "profit_pct":     "profit_pct",
    "cog%":           "cog_pct",
    "cog_pct":        "cog_pct",
    "cvr%":           "cvr_pct",
    "cvr_pct":        "cvr_pct",
    "cpc":            "cpc",
    "refunds":        "refunds",
    "refund%":        "refund_pct",
    "refund_pct":     "refund_pct",
}

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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

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
    if raw is None or str(raw).strip() in ("", "-", "—"):
        return None
    cleaned = re.sub(r"[%,$€£\s]", "", str(raw))
    try:
        return float(cleaned)
    except ValueError:
        return None


def _normalise(text: str) -> str:
    return str(text).strip().lower()


def _extract_rows(payload) -> list:
    """
    Unwrap whatever structure the Apps Script returns into a flat list.
    Handles: raw list, {"data": [...]}, {"rows": [...]}, {"values": [...]}.
    """
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "rows", "values", "result"):
            if key in payload and isinstance(payload[key], list):
                return payload[key]
    raise ValueError(
        f"Unexpected JSON shape from Apps Script. "
        f"Top-level type: {type(payload).__name__}. "
        f"Expected a list or a dict with a 'data'/'rows' key."
    )


def _parse_array_of_arrays(rows: list) -> list[dict]:
    """Handle [[header,...], [val,...], ...] format."""
    if not rows:
        return []

    header_row = rows[0]
    col_map = {}  # index → canonical name
    for idx, cell in enumerate(header_row):
        canonical = COLUMN_MAP.get(_normalise(cell))
        if canonical:
            col_map[idx] = canonical

    if "report_date" not in col_map.values():
        raise ValueError(
            f"No date column found in sheet headers. "
            f"Headers seen: {header_row}. "
            f"Expected one of: {[k for k,v in COLUMN_MAP.items() if v == 'report_date']}"
        )

    out = []
    skipped = 0
    for row_num, raw_row in enumerate(rows[1:], start=2):
        if not any(str(c).strip() for c in raw_row):
            skipped += 1
            continue

        date_idx = next(i for i, n in col_map.items() if n == "report_date")
        date_raw = raw_row[date_idx] if date_idx < len(raw_row) else ""
        if not str(date_raw).strip():
            skipped += 1
            continue

        parsed_date = _parse_date(str(date_raw))
        if parsed_date is None:
            logger.debug("Row %d: skipping unparseable date %r", row_num, date_raw)
            skipped += 1
            continue

        record: dict = {"report_date": parsed_date}
        for idx, canonical in col_map.items():
            if canonical == "report_date":
                continue
            raw_val = raw_row[idx] if idx < len(raw_row) else None
            record[canonical] = _to_float(raw_val)
        out.append(record)

    logger.info("Parsed %d rows (%d skipped).", len(out), skipped)
    return out


def _parse_array_of_objects(rows: list) -> list[dict]:
    """Handle [{date:..., revenue:...}, ...] format."""
    out = []
    skipped = 0
    for row_num, obj in enumerate(rows, start=1):
        if not isinstance(obj, dict):
            skipped += 1
            continue

        # Map object keys → canonical names
        record: dict = {}
        for raw_key, raw_val in obj.items():
            canonical = COLUMN_MAP.get(_normalise(raw_key))
            if canonical:
                if canonical == "report_date":
                    parsed = _parse_date(str(raw_val))
                    if parsed is None:
                        break
                    record["report_date"] = parsed
                else:
                    record[canonical] = _to_float(raw_val)

        if "report_date" not in record:
            skipped += 1
            continue
        out.append(record)

    logger.info("Parsed %d rows (%d skipped).", len(out), skipped)
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_pl_data(store_id: str = "default", url: str | None = None) -> list[dict]:
    """
    Call the Google Apps Script web app and return a list of dicts —
    one per data row — with column names matching the daily_pl schema.

    Args:
        store_id: Identifier for the Shopify store this sheet belongs to.
                  Defaults to 'default' (single-store mode). When multi-store
                  is activated, pass each store's ID so rows are tagged correctly.
        url:      Override the Apps Script URL. Defaults to config.GOOGLE_SCRIPT_URL.
                  Multi-store callers pass the per-store URL from config.GOOGLE_STORE_URLS.
    """
    url = url or config.GOOGLE_SCRIPT_URL
    logger.info("Fetching P&L data | store_id=%s | url=%s", store_id, url)

    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.exceptions.Timeout:
        raise RuntimeError(
            f"Google Apps Script did not respond within {REQUEST_TIMEOUT}s. "
            "Check that the script is deployed and accessible."
        )
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"HTTP error fetching Apps Script: {exc}") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise ValueError(
            f"Apps Script response is not valid JSON. "
            f"First 200 chars: {response.text[:200]!r}"
        ) from exc

    rows = _extract_rows(payload)
    logger.info("Received %d rows from Apps Script.", len(rows))

    if not rows:
        logger.warning("Apps Script returned an empty list.")
        return []

    # Detect format: array-of-arrays vs array-of-objects
    first = rows[0]
    if isinstance(first, list):
        logger.debug("Detected array-of-arrays format.")
        parsed = _parse_array_of_arrays(rows)
    elif isinstance(first, dict):
        logger.debug("Detected array-of-objects format.")
        parsed = _parse_array_of_objects(rows)
    else:
        raise ValueError(
            f"Unexpected row type in Apps Script response: {type(first).__name__}. "
            "Expected list or dict."
        )

    # Tag every row with store_id so pl_processor can upsert against
    # the correct (store_id, report_date) unique key.
    for row in parsed:
        row["store_id"] = store_id

    return parsed
