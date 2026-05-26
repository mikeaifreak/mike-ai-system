"""
sheets_parser.py — Reads P&L rows from the Google Apps Script web app.

Column layout (0-indexed), confirmed from Mike's Excel file:

  MAY+ format — 16 columns (adspend_pinterest added May 2026)
  ─────────────────────────────────────────────────────────────
  A(0)  date               datetime → .date()
  B(1)  revenue            WRITE — Shopify
  C(2)  cog                READ ONLY — Mike enters manually
  D(3)  adspend_google     WRITE — Google Ads
  E(4)  adspend_pinterest  WRITE — Pinterest Ads (MAY+ only)
  F(5)  mediabuying        auto-calculated, READ ONLY
  G(6)  employee_cost      auto-calculated, READ ONLY
  H(7)  transaction_fee    auto-calculated, READ ONLY
  I(8)  profit             auto-calculated, READ ONLY
  J(9)  roas               auto-calculated, READ ONLY
  K(10) profit_pct         auto-calculated, READ ONLY
  L(11) cog_pct            auto-calculated, READ ONLY
  M(12) cvr_pct            auto-calculated, READ ONLY
  N(13) cpc                auto-calculated, READ ONLY
  O(14) refunds            WRITE — Shopify
  P(15) refund_pct         auto-calculated, READ ONLY

  APR format — 15 columns (no adspend_pinterest)
  ─────────────────────────────────────────────────────────────
  A(0)  date
  B(1)  revenue
  C(2)  cog
  D(3)  adspend_google
  E(4)  mediabuying        ← shifted left by 1
  F(5)  employee_cost
  G(6)  transaction_fee
  H(7)  profit
  I(8)  roas
  J(9)  profit_pct
  K(10) cog_pct
  L(11) cvr_pct
  M(12) cpc
  N(13) refunds
  O(14) refund_pct

Skip rules:
  • Row is entirely empty → skip
  • revenue == 0 AND adspend_google == 0 → skip (no data entered yet)
  • '#DIV/0!' and other Excel error strings → None
"""

import logging
import re
from datetime import datetime, date
from typing import Optional

import requests

import config

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30

# ─── Column index maps ────────────────────────────────────────────────────────

_LAYOUT_MAY = {
    0:  "report_date",
    1:  "revenue",
    2:  "cog",
    3:  "adspend_google",
    4:  "adspend_pinterest",
    5:  "mediabuying",
    6:  "employee_cost",
    7:  "transaction_fee",
    8:  "profit",
    9:  "roas",
    10: "profit_pct",
    11: "cog_pct",
    12: "cvr_pct",
    13: "cpc",
    14: "refunds",
    15: "refund_pct",
}

_LAYOUT_APR = {
    0:  "report_date",
    1:  "revenue",
    2:  "cog",
    3:  "adspend_google",
    4:  "mediabuying",
    5:  "employee_cost",
    6:  "transaction_fee",
    7:  "profit",
    8:  "roas",
    9:  "profit_pct",
    10: "cog_pct",
    11: "cvr_pct",
    12: "cpc",
    13: "refunds",
    14: "refund_pct",
}

# Fallback: header-name → canonical field (for array-of-objects format)
_HEADER_MAP = {
    "date": "report_date", "datum": "report_date", "spalte 1": "report_date",
    "_date_iso": "report_date",
    "revenue": "revenue",
    "cog": "cog",
    "adspend google": "adspend_google", "adspend_google": "adspend_google",
    "adspend pinterest": "adspend_pinterest", "adspend_pinterest": "adspend_pinterest",
    "mediabuying": "mediabuying", "media buying": "mediabuying",
    "employee cost": "employee_cost", "employee_cost": "employee_cost",
    "transaction fee": "transaction_fee", "transaction_fee": "transaction_fee",
    "profit": "profit",
    "roas": "roas",
    "profit%": "profit_pct", "profit_pct": "profit_pct",
    "cog%": "cog_pct", "cog_pct": "cog_pct",
    "cvr%": "cvr_pct", "cvr_pct": "cvr_pct",
    "cpc": "cpc",
    "refunds": "refunds",
    "refund%": "refund_pct", "refund_pct": "refund_pct",
}

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _detect_layout(col_count: int) -> dict:
    """Return the correct index→field map based on column count."""
    if col_count >= 16:
        return _LAYOUT_MAY
    if col_count == 15:
        return _LAYOUT_APR
    logger.warning(
        "Unexpected column count %d — falling back to APR layout (15-col). "
        "Expected 15 (APR) or 16 (MAY+).",
        col_count,
    )
    return _LAYOUT_APR


def _parse_date(raw) -> Optional[date]:
    """Convert whatever the Apps Script sends into a Python date object."""
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    if isinstance(raw, datetime):
        return raw.date()
    s = str(raw).strip()
    if not s or s in ("-", "—"):
        return None
    # ISO datetime with timezone: "2026-05-01T00:00:00.000Z"
    if "T" in s:
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
        except ValueError:
            pass
    # Plain ISO date: "2026-05-01"
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        pass
    # European formats
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    logger.warning("Could not parse date: %r", raw)
    return None


def _to_float(raw) -> Optional[float]:
    """Convert a cell value to float, returning None for errors/blanks."""
    if raw is None:
        return None
    s = str(raw).strip()
    if s in ("", "-", "—", "#DIV/0!", "#N/A", "#VALUE!", "#REF!", "#NULL!", "#NAME?"):
        return None
    cleaned = re.sub(r"[%,$€£\s]", "", s)
    if not cleaned:
        return None
    try:
        return float(cleaned.replace(",", "."))
    except ValueError:
        return None


def _is_header_row(row: list) -> bool:
    """Return True if row[0] looks like a column label rather than a date."""
    if not row:
        return False
    first = str(row[0]).strip().lower()
    if first in ("date", "datum", "spalte 1", "day", ""):
        return True
    return _parse_date(row[0]) is None


def _extract_rows(payload) -> list:
    """Unwrap whatever envelope the Apps Script returns into a flat list."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "rows", "values", "result"):
            if key in payload and isinstance(payload[key], list):
                return payload[key]
    raise ValueError(
        f"Unexpected Apps Script response shape. "
        f"Type: {type(payload).__name__}. "
        "Expected a list or a dict with a 'data'/'rows' key."
    )


# ─── Parsers ──────────────────────────────────────────────────────────────────

def _parse_array_rows(rows: list, layout: dict, store_id: str) -> list[dict]:
    """Parse [[val, val, ...], ...] rows using a fixed index→field map."""
    out = []
    skipped = 0

    for row_num, raw_row in enumerate(rows, start=1):
        if not raw_row or not any(str(c).strip() for c in raw_row):
            skipped += 1
            continue

        raw_date = raw_row[0] if raw_row else None
        if raw_date is None or str(raw_date).strip() == "":
            skipped += 1
            continue

        parsed_date = _parse_date(raw_date)
        if parsed_date is None:
            logger.debug("Row %d: skipping unparseable date %r", row_num, raw_date)
            skipped += 1
            continue

        record: dict = {"report_date": parsed_date, "store_id": store_id}
        for idx, field in layout.items():
            if field == "report_date":
                continue
            val = raw_row[idx] if idx < len(raw_row) else None
            record[field] = _to_float(val)

        # Skip rows with no meaningful data (no revenue and no ad spend)
        rev = record.get("revenue") or 0.0
        ads = record.get("adspend_google") or 0.0
        if rev == 0.0 and ads == 0.0:
            skipped += 1
            continue

        out.append(record)

    logger.info("Parsed %d rows (%d skipped).", len(out), skipped)
    return out


def _parse_object_rows(rows: list, store_id: str) -> list[dict]:
    """Parse [{header: value, ...}, ...] rows using header-name mapping."""
    out = []
    skipped = 0

    for obj in rows:
        if not isinstance(obj, dict):
            skipped += 1
            continue

        record: dict = {"store_id": store_id}
        date_ok = False
        for raw_key, raw_val in obj.items():
            field = _HEADER_MAP.get(str(raw_key).strip().lower())
            if not field:
                continue
            if field == "report_date":
                parsed = _parse_date(raw_val)
                if parsed is None:
                    break
                record["report_date"] = parsed
                date_ok = True
            else:
                record[field] = _to_float(raw_val)

        if not date_ok:
            skipped += 1
            continue

        rev = record.get("revenue") or 0.0
        ads = record.get("adspend_google") or 0.0
        if rev == 0.0 and ads == 0.0:
            skipped += 1
            continue

        out.append(record)

    logger.info("Parsed %d rows (%d skipped).", len(out), skipped)
    return out


def _parse_data_rows(raw_rows: list, store_id: str) -> list[dict]:
    """Dispatch to the correct parser based on row type."""
    if not raw_rows:
        return []

    first = raw_rows[0]

    if isinstance(first, dict):
        return _parse_object_rows(raw_rows, store_id)

    if isinstance(first, list):
        rows = raw_rows
        if _is_header_row(rows[0]):
            col_count = len(rows[0])
            rows = rows[1:]
        else:
            # Infer column count from first few data rows
            col_count = max((len(r) for r in rows[:5] if r), default=15)
        layout = _detect_layout(col_count)
        return _parse_array_rows(rows, layout, store_id)

    raise ValueError(
        f"Unexpected row type: {type(first).__name__}. Expected list or dict."
    )


# ─── Public API ───────────────────────────────────────────────────────────────

def fetch_pl_data(store_id: str = "default", url: str | None = None) -> list[dict]:
    """
    Call the Google Apps Script web app and return a list of row dicts,
    one per data row, with field names matching the daily_pl schema.

    Args:
        store_id: Shopify store identifier. Defaults to 'default'.
        url:      Apps Script URL override. Defaults to config.GOOGLE_SCRIPT_URL.
    """
    url = url or config.GOOGLE_SCRIPT_URL
    logger.info("Fetching P&L data | store_id=%s | url=%s", store_id, url)

    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.exceptions.Timeout:
        raise RuntimeError(
            f"Apps Script did not respond in {REQUEST_TIMEOUT}s. "
            "Verify the script is deployed with 'Anyone' access."
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

    raw_rows = _extract_rows(payload)
    logger.info("Received %d raw rows.", len(raw_rows))

    return _parse_data_rows(raw_rows, store_id)
