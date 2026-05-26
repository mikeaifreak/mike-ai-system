"""
sheets_writer.py — Writes API-sourced values back to the P&L Google Sheet.

Architecture:
  Each data-source pipeline calls write_values() to POST field values to the
  Apps Script web app. The Apps Script writes to the correct cells for that date.
  Excel formulas in the sheet then auto-calculate the remaining columns.
  sync_only (06:50) reads the full calculated row and stores in PostgreSQL.

Writable columns only:
  B(1)  revenue           ← Shopify
  D(3)  adspend_google    ← Google Ads
  E(4)  adspend_pinterest ← Pinterest Ads (MAY+ only)
  O(14) refunds           ← Shopify

Never written by this module:
  C(2)  cog               ← Mike enters manually
  F–P   formula columns   ← auto-calculated, read-only

Apps Script (doPost) requirements:
  The Apps Script web app must implement doPost(e) accepting JSON:
    {
      "action":            "write",
      "date":              "YYYY-MM-DD",
      "revenue":           <number|null>,
      "adspend_google":    <number|null>,
      "adspend_pinterest": <number|null>,
      "refunds":           <number|null>
    }
  Absent/null fields are skipped. Column C (COG) is never touched.
  The response should confirm success: {"success": true}.

Apps Script (doGet?date=) requirements:
  GET requests with ?date=YYYY-MM-DD should return just that row's data
  so read_row_for_date() can fetch the calculated values after writing.
"""

import logging
import time
from datetime import date
from typing import Optional

import requests

import config

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30
READ_BACK_DELAY_S = 2  # seconds to wait for formula recalculation after write

# Writable field → sheet column letter (for logging)
WRITABLE_COLS = {
    "revenue":           "B",
    "adspend_google":    "D",
    "adspend_pinterest": "E",
    "refunds":           "O",
}


def write_values(
    report_date: date,
    store_id: str = "default",
    url: Optional[str] = None,
    *,
    revenue: Optional[float] = None,
    adspend_google: Optional[float] = None,
    adspend_pinterest: Optional[float] = None,
    refunds: Optional[float] = None,
) -> bool:
    """
    POST one or more field values for a single date to the Apps Script.

    Only non-None fields are sent — the Apps Script skips absent fields
    and never touches column C (COG). Pass only the fields this pipeline
    stage is responsible for.

    Returns True on success, False on failure (errors are logged, not raised,
    so the calling pipeline continues with other dates).
    """
    url = url or config.GOOGLE_SCRIPT_URL

    payload: dict = {
        "action": "write",
        "date":   report_date.isoformat(),
    }
    if revenue           is not None:
        payload["revenue"]           = revenue
    if adspend_google    is not None:
        payload["adspend_google"]    = adspend_google
    if adspend_pinterest is not None:
        payload["adspend_pinterest"] = adspend_pinterest
    if refunds           is not None:
        payload["refunds"]           = refunds

    written_cols = [WRITABLE_COLS[k] for k in payload if k in WRITABLE_COLS]
    if not written_cols:
        logger.debug("write_values called with no fields to write | date=%s", report_date)
        return True

    logger.info(
        "Writing to sheet | store=%s | date=%s | cols=%s",
        store_id, report_date, written_cols,
    )

    try:
        resp = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        logger.info("  sheet write OK | date=%s | cols=%s", report_date, written_cols)
        return True
    except requests.exceptions.Timeout:
        logger.warning(
            "Sheet write timed out after %ds | date=%s | cols=%s",
            REQUEST_TIMEOUT, report_date, written_cols,
        )
        return False
    except requests.exceptions.RequestException as exc:
        logger.warning(
            "Sheet write failed | date=%s | cols=%s | error=%s",
            report_date, written_cols, exc,
        )
        return False


def read_row_for_date(
    report_date: date,
    store_id: str = "default",
    url: Optional[str] = None,
) -> Optional[dict]:
    """
    GET a single row from the Apps Script by passing ?date=YYYY-MM-DD.
    The Apps Script should return just that row's data.

    Returns a parsed row dict (with store_id set) or None on failure.
    """
    from sheets_parser import _parse_data_rows  # local import avoids circular

    url = url or config.GOOGLE_SCRIPT_URL
    try:
        resp = requests.get(
            url,
            params={"date": report_date.isoformat()},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        logger.warning(
            "read_row_for_date failed | date=%s | error=%s", report_date, exc
        )
        return None

    # Normalise: Apps Script may return a single row, list, or envelope
    if isinstance(payload, dict):
        if "data" in payload:
            rows = payload["data"] if isinstance(payload["data"], list) else [payload["data"]]
        else:
            rows = [payload]
    elif isinstance(payload, list):
        rows = payload
    else:
        return None

    parsed = _parse_data_rows(rows, store_id)
    # Return the row matching the requested date (or first row if only one)
    for row in parsed:
        if row.get("report_date") == report_date:
            return row
    return parsed[0] if len(parsed) == 1 else None


def write_and_read(
    report_date: date,
    store_id: str = "default",
    url: Optional[str] = None,
    *,
    revenue: Optional[float] = None,
    adspend_google: Optional[float] = None,
    adspend_pinterest: Optional[float] = None,
    refunds: Optional[float] = None,
) -> Optional[dict]:
    """
    Write values to the sheet, wait READ_BACK_DELAY_S for formula
    recalculation, then read back the full row including all auto-calculated
    columns (profit, roas, cpc, cvr_pct, etc.).

    Use this when the calling code needs the calculated values immediately.
    In the normal daily pipeline, sync_only (06:50) handles the readback,
    so individual pullers call write_values() directly without the wait.

    Returns the full parsed row dict or None if the readback fails.
    """
    success = write_values(
        report_date, store_id, url,
        revenue=revenue,
        adspend_google=adspend_google,
        adspend_pinterest=adspend_pinterest,
        refunds=refunds,
    )
    if not success:
        return None

    logger.debug(
        "Waiting %ds for sheet formula recalculation | date=%s",
        READ_BACK_DELAY_S, report_date,
    )
    time.sleep(READ_BACK_DELAY_S)

    return read_row_for_date(report_date, store_id, url)
