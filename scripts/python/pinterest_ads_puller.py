"""
pinterest_ads_puller.py — Reads Pinterest Ads spend from Google Sheets.

Architecture:
  1. A Pinterest Ads Script runs inside each Pinterest Ads account daily at
     06:00, writing per-campaign rows to a Google Sheet.
  2. Each sheet is exposed via a Google Apps Script web app URL.
  3. This module reads those URLs, aggregates spend per day, and writes
     adspend_pinterest to the P&L sheet via sheets_writer.write_values().
  4. sync_only (06:50) reads the complete P&L row and stores it in PostgreSQL.

Sheet column layout (written by pinterest-ads-script.js):
  Date | Account Name | Campaign | Spend | Impressions | Clicks | Conversions | CPC

Config:
  Single store:  PINTEREST_ADS_SHEET_URLS=https://script.google.com/...
  Multi-store:   PINTEREST_ADS_SHEET_URLS=store_nl:https://...,store_de:https://...
  Parsed in config.py → PINTEREST_ADS_STORE_SHEET_URLS: dict[store_id, url]

Pipeline position:
  06:40  pull_shopify        ← writes revenue(B) + refunds(O) to P&L sheet
  06:45  pull_google_ads     ← writes adspend_google(D) to P&L sheet
  06:46  pull_pinterest_ads  ← this module — writes adspend_pinterest(E)
  06:50  sync_only           ← reads full P&L row, stores in PostgreSQL
  07:00  morning_report      ← Slack report from PostgreSQL
"""

import logging
import time
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

import psycopg2
import requests

import config
import sheets_writer

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30

# Column name → canonical key (case-insensitive, same pattern as google_ads_puller)
COLUMN_MAP = {
    "date":         "report_date",
    "spend":        "spend",
    "cost":         "spend",
    "impressions":  "impressions",
    "clicks":       "clicks",
    "conversions":  "conversions",
    "cpc":          "cpc",
}


# ─── HTTP fetch ───────────────────────────────────────────────────────────────

def _fetch_json(url: str) -> list:
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.exceptions.Timeout:
        raise RuntimeError(
            f"Pinterest Ads sheet URL did not respond in {REQUEST_TIMEOUT}s: {url}"
        )
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"HTTP error fetching Pinterest Ads sheet: {exc}") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise ValueError(
            f"Response is not valid JSON. First 200 chars: {response.text[:200]!r}"
        ) from exc

    if isinstance(payload, dict):
        for key in ("data", "rows", "values", "result"):
            if key in payload and isinstance(payload[key], list):
                return payload[key]
        raise ValueError(
            f"Unexpected dict shape — no 'data'/'rows' key. Keys: {list(payload)}"
        )
    if isinstance(payload, list):
        return payload
    raise ValueError(f"Unexpected JSON type: {type(payload).__name__}")


# ─── Row parsing ──────────────────────────────────────────────────────────────

def _parse_rows(raw_rows: list) -> list[dict]:
    """Handle both array-of-arrays (first row = headers) and array-of-objects."""
    if not raw_rows:
        return []

    first = raw_rows[0]

    if isinstance(first, list):
        col_map = {}
        for idx, cell in enumerate(first):
            key = COLUMN_MAP.get(str(cell).strip().lower())
            if key:
                col_map[idx] = key
        out = []
        for row in raw_rows[1:]:
            if not any(str(c).strip() for c in row):
                continue
            record = {key: row[idx] if idx < len(row) else None
                      for idx, key in col_map.items()}
            out.append(record)
        return out

    if isinstance(first, dict):
        out = []
        for obj in raw_rows:
            record = {}
            for raw_key, val in obj.items():
                key = COLUMN_MAP.get(str(raw_key).strip().lower())
                if key:
                    record[key] = val
            out.append(record)
        return out

    raise ValueError(f"Unexpected row type: {type(first).__name__}")


def _to_float(val) -> Optional[float]:
    if val is None or str(val).strip() in ("", "-", "—"):
        return None
    try:
        return float(str(val).replace(",", "").replace("$", "").strip())
    except ValueError:
        return None


def _aggregate_by_date(rows: list[dict]) -> dict[date, dict]:
    """Sum spend, clicks, impressions, conversions across all campaigns per date."""
    from datetime import datetime

    DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%m/%d/%Y"]
    totals: dict = defaultdict(lambda: {
        "spend": 0.0, "clicks": 0, "impressions": 0, "conversions": 0.0
    })

    for row in rows:
        raw_date = row.get("report_date")
        if not raw_date:
            continue

        # Handle ISO datetime strings from Apps Script
        s = str(raw_date).strip()
        parsed_date = None
        if "T" in s:
            try:
                parsed_date = datetime.fromisoformat(
                    s.replace("Z", "+00:00")
                ).date()
            except ValueError:
                pass
        if parsed_date is None:
            for fmt in DATE_FORMATS:
                try:
                    parsed_date = datetime.strptime(s, fmt).date()
                    break
                except ValueError:
                    continue
        if parsed_date is None:
            logger.warning("Could not parse date: %r — skipping row", raw_date)
            continue

        d = totals[parsed_date]
        d["spend"]       += _to_float(row.get("spend"))       or 0.0
        d["clicks"]      += int(_to_float(row.get("clicks"))  or 0)
        d["impressions"] += int(_to_float(row.get("impressions")) or 0)
        d["conversions"] += _to_float(row.get("conversions"))  or 0.0

    result = {}
    for dt, d in totals.items():
        spend = d["spend"]
        result[dt] = {
            "adspend_pinterest": round(spend, 4) if spend else None,
        }
    return result


# ─── Sheet write ──────────────────────────────────────────────────────────────

def _write_to_sheet(store_id: str, daily: dict[date, dict]) -> int:
    """Write adspend_pinterest to the P&L sheet for each date."""
    pl_url = config.GOOGLE_SCRIPT_URL
    count = 0
    for report_date, metrics in daily.items():
        adspend = metrics.get("adspend_pinterest")
        if adspend is None:
            continue
        ok = sheets_writer.write_values(
            report_date, store_id, pl_url,
            adspend_pinterest=adspend,
        )
        if ok:
            count += 1
    return count


# ─── Monitoring ───────────────────────────────────────────────────────────────

def _log_agent_run(
    store_id: str,
    status: str,
    duration_ms: int,
    rows_processed: int = 0,
    error_message: Optional[str] = None,
) -> None:
    try:
        with psycopg2.connect(config.POSTGRES_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agent_runs (
                        agent_name, workflow_name, trigger_type, status,
                        rows_processed, duration_ms, error_message,
                        model, finished_at
                    ) VALUES (%s, %s, 'cron', %s, %s, %s, %s, %s, NOW())
                    """,
                    (
                        f"pinterest_ads_puller.{store_id}",
                        "pull_pinterest_ads",
                        status,
                        rows_processed,
                        duration_ms,
                        error_message,
                        "pinterest_ads_script",
                    ),
                )
                conn.commit()
    except Exception as log_exc:
        logger.warning("agent_runs log failed: %s", log_exc)


# ─── Public entry point ───────────────────────────────────────────────────────

def pull_all_stores() -> None:
    """
    Fetch Pinterest Ads spend from each store's Apps Script URL and write
    adspend_pinterest(E) to the corresponding P&L sheet row.

    Skips gracefully if PINTEREST_ADS_SHEET_URLS is not set — the rest of
    the pipeline continues.

    To add a store:
      1. Create a Pinterest Ads Script for that account (similar to
         scripts/pinterest-ads-script.js)
      2. The script writes daily rows to a Google Sheet
      3. Deploy an Apps Script web app on that sheet
      4. Add the URL to PINTEREST_ADS_SHEET_URLS in .env
    """
    if not config.PINTEREST_ADS_STORE_SHEET_URLS:
        logger.warning(
            "PINTEREST_ADS_SHEET_URLS is not set — skipping Pinterest Ads pull. "
            "Set it in .env once the Pinterest Ads Script is installed."
        )
        return

    yesterday = date.today() - timedelta(days=1)
    logger.info(
        "Pinterest Ads pull | date=%s | stores=%s",
        yesterday, list(config.PINTEREST_ADS_STORE_SHEET_URLS.keys()),
    )

    for store_id, url in config.PINTEREST_ADS_STORE_SHEET_URLS.items():
        t0 = time.monotonic()
        logger.info("  [%s] fetching: %s", store_id, url)

        try:
            raw_rows    = _fetch_json(url)
            parsed      = _parse_rows(raw_rows)
            by_date     = _aggregate_by_date(parsed)
            count       = _write_to_sheet(store_id, by_date)
            duration_ms = int((time.monotonic() - t0) * 1000)

            for dt, m in sorted(by_date.items()):
                logger.info(
                    "  [%s] %s  spend_pinterest=$%.2f",
                    store_id, dt,
                    m["adspend_pinterest"] or 0,
                )

            logger.info(
                "  [%s] wrote %d date rows to sheet in %dms",
                store_id, count, duration_ms,
            )
            _log_agent_run(store_id, "success", duration_ms, rows_processed=count)

        except Exception as exc:
            duration_ms = int((time.monotonic() - t0) * 1000)
            logger.exception("  [%s] FAILED: %s", store_id, exc)
            _log_agent_run(store_id, "error", duration_ms, error_message=str(exc))
