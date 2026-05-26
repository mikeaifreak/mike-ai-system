"""
google_ads_puller.py — Reads Google Ads spend data from Google Sheets.

Architecture:
  1. A Google Ads Script (scripts/google-ads-script.js) runs inside each
     Google Ads account daily at 06:00, writing per-campaign rows to a Sheet.
  2. Each sheet is exposed via a Google Apps Script web app URL.
  3. This module reads those URLs, aggregates spend across campaigns per day,
     and upserts adspend_google + cpc + cvr_pct into daily_pl.

This means NO Google Ads API credentials are needed in Python — all auth
is handled inside the Google Ads Script running in Mike's account.

Sheet column layout (written by google-ads-script.js):
  Date | Account Name | Campaign | Spend | Impressions | Clicks | Conversions | CPC

Config:
  Single store:   GOOGLE_ADS_SHEET_URLS=https://script.google.com/...
  Multi-store:    GOOGLE_ADS_SHEET_URLS=store_nl:https://...,store_de:https://...
  Parsed in config.py → GOOGLE_ADS_STORE_SHEET_URLS: dict[store_id, url]

Pipeline position:
  06:45  pull_google_ads  ← this module (reads Sheet, upserts ad spend)
  06:50  sync_only        ← sheets_parser.py (fills revenue, COG, etc.)
  07:00  morning_report   ← complete data available for Slack report
"""

import logging
import time
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

import psycopg2
import requests

import config

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30  # seconds

# Column name → canonical key (case-insensitive)
COLUMN_MAP = {
    "date":         "report_date",
    "spend":        "spend",
    "cost":         "spend",
    "impressions":  "impressions",
    "clicks":       "clicks",
    "conversions":  "conversions",
    "cpc":          "cpc",
    # account name / campaign are metadata, not stored in daily_pl
}

# Only update ad spend fields on conflict — revenue, COG etc. are owned
# by the sheet sync and pl_processor.py uses COALESCE to protect these.
UPSERT_ADS_SQL = """
INSERT INTO daily_pl (
    store_id, report_date, adspend_google, cpc, cvr_pct, source, synced_at
) VALUES (
    %(store_id)s, %(report_date)s,
    %(adspend_google)s, %(cpc)s, %(cvr_pct)s,
    'google_ads', NOW()
)
ON CONFLICT (store_id, report_date) DO UPDATE SET
    adspend_google = EXCLUDED.adspend_google,
    cpc            = EXCLUDED.cpc,
    cvr_pct        = EXCLUDED.cvr_pct,
    synced_at      = NOW(),
    updated_at     = NOW()
"""


# ---------------------------------------------------------------------------
# HTTP fetch + JSON parse (mirrors sheets_parser.py pattern)
# ---------------------------------------------------------------------------

def _fetch_json(url: str) -> list:
    """Call the Apps Script web app and return a flat list of rows."""
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.exceptions.Timeout:
        raise RuntimeError(
            f"Apps Script URL did not respond within {REQUEST_TIMEOUT}s: {url}"
        )
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"HTTP error fetching Ads sheet: {exc}") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise ValueError(
            f"Response is not valid JSON. First 200 chars: {response.text[:200]!r}"
        ) from exc

    # Unwrap envelope formats: {"data":[...]}, {"rows":[...]}, {"values":[...]}
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


def _parse_rows(raw_rows: list) -> list[dict]:
    """
    Parse the raw JSON rows from the Apps Script into normalised dicts.
    Handles both array-of-arrays (first row = headers) and array-of-objects.
    """
    if not raw_rows:
        return []

    first = raw_rows[0]

    if isinstance(first, list):
        # Array-of-arrays: first row is headers
        header_row = first
        col_map = {}  # index → canonical key
        for idx, cell in enumerate(header_row):
            key = COLUMN_MAP.get(str(cell).strip().lower())
            if key:
                col_map[idx] = key

        out = []
        for row in raw_rows[1:]:
            if not any(str(c).strip() for c in row):
                continue
            record = {}
            for idx, key in col_map.items():
                record[key] = row[idx] if idx < len(row) else None
            out.append(record)
        return out

    if isinstance(first, dict):
        # Array-of-objects
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
    """
    Sum spend, clicks, impressions, conversions across all campaigns per date.
    CPC and CVR% are recomputed from the aggregated totals for accuracy.
    """
    from datetime import datetime

    DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%m/%d/%Y"]
    totals: dict = defaultdict(lambda: {
        "spend": 0.0, "clicks": 0, "impressions": 0, "conversions": 0.0
    })

    for row in rows:
        raw_date = row.get("report_date")
        if not raw_date:
            continue

        parsed_date = None
        for fmt in DATE_FORMATS:
            try:
                parsed_date = datetime.strptime(str(raw_date).strip(), fmt).date()
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
        clicks = d["clicks"]
        spend  = d["spend"]
        result[dt] = {
            "adspend_google": round(spend, 4) if spend else None,
            "cpc":     round(spend / clicks, 4) if clicks > 0 else None,
            "cvr_pct": round((d["conversions"] / clicks) * 100, 4) if clicks > 0 else None,
        }
    return result


# ---------------------------------------------------------------------------
# DB write
# ---------------------------------------------------------------------------

def _upsert_store(store_id: str, daily: dict[date, dict]) -> int:
    count = 0
    with psycopg2.connect(config.POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            for report_date, metrics in daily.items():
                cur.execute(UPSERT_ADS_SQL, {
                    "store_id":       store_id,
                    "report_date":    report_date,
                    "adspend_google": metrics["adspend_google"],
                    "cpc":            metrics["cpc"],
                    "cvr_pct":        metrics["cvr_pct"],
                })
                count += 1
        conn.commit()
    return count


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
                        f"google_ads_puller.{store_id}",
                        "pull_google_ads",
                        status,
                        rows_processed,
                        duration_ms,
                        error_message,
                        "google_ads_script",
                    ),
                )
                conn.commit()
    except Exception as log_exc:
        logger.warning("agent_runs log failed: %s", log_exc)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def pull_all_stores() -> None:
    """
    Fetch ad spend from each store's Apps Script URL and upsert into daily_pl.

    Reads GOOGLE_ADS_STORE_SHEET_URLS from config (dict[store_id → url]).
    Skips gracefully if the var is not set — the rest of the pipeline continues.

    To add a new store:
      1. Mike installs google-ads-script.js in that Google Ads account
      2. The script writes to a new Google Sheet
      3. Deploy an Apps Script web app on that sheet
      4. Add the URL to GOOGLE_ADS_SHEET_URLS in .env
    """
    if not config.GOOGLE_ADS_STORE_SHEET_URLS:
        logger.warning(
            "GOOGLE_ADS_SHEET_URLS is not set — skipping Google Ads pull. "
            "Set it in .env once Mike has installed google-ads-script.js."
        )
        return

    yesterday = date.today() - timedelta(days=1)
    logger.info(
        "Google Ads pull | date=%s | stores=%s",
        yesterday, list(config.GOOGLE_ADS_STORE_SHEET_URLS.keys()),
    )

    for store_id, url in config.GOOGLE_ADS_STORE_SHEET_URLS.items():
        t0 = time.monotonic()
        logger.info("  [%s] fetching: %s", store_id, url)

        try:
            raw_rows   = _fetch_json(url)
            parsed     = _parse_rows(raw_rows)
            by_date    = _aggregate_by_date(parsed)
            count      = _upsert_store(store_id, by_date)
            duration_ms = int((time.monotonic() - t0) * 1000)

            for dt, m in sorted(by_date.items()):
                logger.info(
                    "  [%s] %s  spend=$%.2f  cpc=%s  cvr=%s",
                    store_id, dt,
                    m["adspend_google"] or 0,
                    f"${m['cpc']:.4f}" if m["cpc"] else "—",
                    f"{m['cvr_pct']:.2f}%" if m["cvr_pct"] else "—",
                )

            logger.info("  [%s] upserted %d date rows in %dms", store_id, count, duration_ms)
            _log_agent_run(store_id, "success", duration_ms, rows_processed=count)

        except Exception as exc:
            duration_ms = int((time.monotonic() - t0) * 1000)
            logger.exception("  [%s] FAILED: %s", store_id, exc)
            _log_agent_run(store_id, "error", duration_ms, error_message=str(exc))
