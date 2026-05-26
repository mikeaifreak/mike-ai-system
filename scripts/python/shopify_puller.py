"""
shopify_puller.py — Pulls order revenue and refunds from Shopify Admin REST API.

For each day in the lookback window (yesterday + 6 prior days):
  1. Fetch all orders created that day via paginated REST API
  2. revenue = sum(total_price) for all orders
  3. refunds = sum of successful refund transaction amounts
  4. Write revenue to P&L sheet column B via sheets_writer
  5. Write refunds to P&L sheet column O via sheets_writer
  6. Upsert raw orders into shopify_orders table

Config (all from .env):
  SHOPIFY_STORE_URL  = frugaze.myshopify.com
  SHOPIFY_API_TOKEN  = shpat_...  (Custom App Admin API access token)

Pipeline position:
  06:40  pull_shopify  <- this module
  06:45  pull_google_ads
  06:46  pull_pinterest_ads
  06:50  sync_only     <- reads full P&L row, stores in PostgreSQL
"""

import json
import logging
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import psycopg2
import psycopg2.extras
import requests

import config
import sheets_writer

logger = logging.getLogger(__name__)

API_VERSION    = "2024-04"
REQUEST_TIMEOUT = 30
LOOKBACK_DAYS  = 7

# Fields fetched per order — keeps response payloads small
ORDER_FIELDS = (
    "id,order_number,name,created_at,total_price,subtotal_price,"
    "total_discounts,total_tax,financial_status,fulfillment_status,"
    "currency,email,line_items,refunds"
)


# ---------------------------------------------------------------------------
# Shopify REST API helpers
# ---------------------------------------------------------------------------

def _api_url(path: str) -> str:
    store = config.SHOPIFY_STORE_URL.rstrip("/")
    if not store.startswith("http"):
        store = "https://" + store
    return store + "/admin/api/" + API_VERSION + path


def _headers() -> dict:
    return {"X-Shopify-Access-Token": config.SHOPIFY_API_TOKEN}


def _parse_next_link(link_header: str) -> Optional[str]:
    """Extract the next-page URL from a Shopify Link response header."""
    if not link_header:
        return None
    for part in link_header.split(","):
        part = part.strip()
        if 'rel="next"' in part:
            match = re.search(r"<([^>]+)>", part)
            if match:
                return match.group(1)
    return None


def _fetch_orders_for_day(target_date: date) -> list:
    """
    Fetch all orders created on target_date (Amsterdam timezone).
    Handles cursor-based pagination automatically.
    """
    # Amsterdam offset: CEST = UTC+2 (late Mar–late Oct), CET = UTC+1 otherwise
    # Use a simple check: DST is active roughly Apr–Oct
    month = target_date.month
    ams_offset = "+02:00" if 4 <= month <= 10 else "+01:00"

    date_min = target_date.strftime("%Y-%m-%dT00:00:00") + ams_offset
    date_max = target_date.strftime("%Y-%m-%dT23:59:59") + ams_offset

    logger.info("  Fetching orders | date=%s | window=%s to %s", target_date, date_min, date_max)

    url = _api_url("/orders.json")
    params = {
        "status":          "any",
        "created_at_min":  date_min,
        "created_at_max":  date_max,
        "limit":           250,
        "fields":          ORDER_FIELDS,
    }

    all_orders = []
    page = 1

    while url:
        try:
            resp = requests.get(
                url,
                headers=_headers(),
                params=params,
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
        except requests.exceptions.Timeout:
            raise RuntimeError(
                "Shopify API timed out after {}s (date={})".format(REQUEST_TIMEOUT, target_date)
            )
        except requests.exceptions.RequestException as exc:
            raise RuntimeError("Shopify API error: {}".format(exc)) from exc

        data = resp.json()
        if "errors" in data:
            raise RuntimeError("Shopify API returned error: {}".format(data["errors"]))

        orders = data.get("orders", [])
        all_orders.extend(orders)
        logger.info("    Page %d: %d orders", page, len(orders))

        # Follow cursor-based pagination
        url = _parse_next_link(resp.headers.get("Link", ""))
        params = None  # page_info is embedded in the next URL
        page += 1

    return all_orders


# ---------------------------------------------------------------------------
# Revenue + refund calculation
# ---------------------------------------------------------------------------

def _calc_refund_total(order: dict) -> float:
    """Sum all successful refund transaction amounts for one order."""
    total = 0.0
    for refund in (order.get("refunds") or []):
        for txn in (refund.get("transactions") or []):
            if txn.get("kind") == "refund" and txn.get("status") == "success":
                total += float(txn.get("amount") or 0)
    return total


def _aggregate_daily(orders: list) -> dict:
    """
    Group orders by calendar date (Amsterdam timezone) and compute:
      revenue = sum(total_price)
      refunds = sum of all refund transaction amounts
    Returns dict[date_str → {revenue, refunds, order_count}]
    """
    daily: dict = {}

    for order in orders:
        created_raw = order.get("created_at", "")
        if not created_raw:
            continue
        # Parse ISO 8601 with timezone, convert to Amsterdam date
        try:
            # Python 3.7+ can parse this directly
            created_utc = datetime.fromisoformat(
                created_raw.replace("Z", "+00:00")
            ).astimezone(timezone.utc)
        except ValueError:
            logger.warning("Could not parse order date: %r", created_raw)
            continue

        # Shift to Amsterdam local date
        month = created_utc.month
        ams_hours = 2 if 4 <= month <= 10 else 1
        ams_date = (created_utc + timedelta(hours=ams_hours)).date()
        key = ams_date

        if key not in daily:
            daily[key] = {"revenue": 0.0, "refunds": 0.0, "order_count": 0}

        daily[key]["revenue"]     += float(order.get("total_price") or 0)
        daily[key]["refunds"]     += _calc_refund_total(order)
        daily[key]["order_count"] += 1

    return daily


# ---------------------------------------------------------------------------
# Sheet write
# ---------------------------------------------------------------------------

def _write_daily_to_sheet(daily: dict, store_id: str) -> int:
    """Write revenue(B) and refunds(O) to P&L sheet for each date."""
    pl_url = config.GOOGLE_SCRIPT_URL
    count = 0
    for report_date, metrics in sorted(daily.items()):
        ok = sheets_writer.write_values(
            report_date, store_id, pl_url,
            revenue=round(metrics["revenue"], 2),
            refunds=round(metrics["refunds"], 2),
        )
        if ok:
            count += 1
            logger.info(
                "  Sheet write OK | date=%s | revenue=%.2f | refunds=%.2f | orders=%d",
                report_date,
                metrics["revenue"],
                metrics["refunds"],
                metrics["order_count"],
            )
        else:
            logger.warning("  Sheet write FAILED | date=%s", report_date)
    return count


# ---------------------------------------------------------------------------
# PostgreSQL — raw order storage
# ---------------------------------------------------------------------------

UPSERT_ORDER_SQL = """
INSERT INTO shopify_orders (
    shopify_order_id, order_date, order_number,
    customer_email, total_price, subtotal_price,
    total_discounts, total_tax, financial_status,
    fulfillment_status, currency, line_items, raw_payload, synced_at
) VALUES (
    %(shopify_order_id)s, %(order_date)s, %(order_number)s,
    %(customer_email)s, %(total_price)s, %(subtotal_price)s,
    %(total_discounts)s, %(total_tax)s, %(financial_status)s,
    %(fulfillment_status)s, %(currency)s, %(line_items)s, %(raw_payload)s,
    NOW()
)
ON CONFLICT (shopify_order_id) DO UPDATE SET
    financial_status   = EXCLUDED.financial_status,
    fulfillment_status = EXCLUDED.fulfillment_status,
    total_price        = EXCLUDED.total_price,
    raw_payload        = EXCLUDED.raw_payload,
    synced_at          = NOW()
"""


def _store_raw_orders(orders: list) -> int:
    """Upsert raw order data into shopify_orders table."""
    if not orders:
        return 0

    count = 0
    with psycopg2.connect(config.POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            for order in orders:
                created_raw = order.get("created_at", "")
                try:
                    order_date = datetime.fromisoformat(
                        created_raw.replace("Z", "+00:00")
                    ).date()
                except (ValueError, AttributeError):
                    order_date = None

                cur.execute(UPSERT_ORDER_SQL, {
                    "shopify_order_id":  str(order.get("id")),
                    "order_date":        order_date,
                    "order_number":      order.get("order_number") or order.get("name"),
                    "customer_email":    order.get("email"),
                    "total_price":       order.get("total_price"),
                    "subtotal_price":    order.get("subtotal_price"),
                    "total_discounts":   order.get("total_discounts"),
                    "total_tax":         order.get("total_tax"),
                    "financial_status":  order.get("financial_status"),
                    "fulfillment_status":order.get("fulfillment_status"),
                    "currency":          order.get("currency"),
                    "line_items":        json.dumps(order.get("line_items") or []),
                    "raw_payload":       json.dumps(order),
                })
                count += 1
        conn.commit()
    return count


# ---------------------------------------------------------------------------
# agent_runs logging
# ---------------------------------------------------------------------------

def _log_agent_run(
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
                        rows_processed, duration_ms, error_message, finished_at
                    ) VALUES (%s, %s, 'cron', %s, %s, %s, %s, NOW())
                    """,
                    (
                        "shopify_puller",
                        "pull_shopify",
                        status,
                        rows_processed,
                        duration_ms,
                        error_message,
                    ),
                )
                conn.commit()
    except Exception as log_exc:
        logger.warning("agent_runs log failed: %s", log_exc)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(store_id: str = "default", lookback_days: int = LOOKBACK_DAYS) -> dict:
    """
    Pull orders for yesterday + lookback_days from Shopify.
    Writes revenue(B) and refunds(O) to the P&L sheet.
    Stores raw orders in PostgreSQL.

    Returns a summary dict with totals for the caller to log.
    """
    if not config.SHOPIFY_STORE_URL or not config.SHOPIFY_API_TOKEN:
        logger.warning(
            "SHOPIFY_STORE_URL or SHOPIFY_API_TOKEN not set — skipping Shopify pull."
        )
        return {}

    t0 = time.monotonic()
    today     = date.today()
    yesterday = today - timedelta(days=1)

    dates_to_pull = [yesterday - timedelta(days=i) for i in range(lookback_days)]
    logger.info(
        "Shopify pull | store=%s | lookback=%dd | dates=%s to %s",
        config.SHOPIFY_STORE_URL, lookback_days,
        dates_to_pull[-1], dates_to_pull[0],
    )

    all_orders = []
    all_daily: dict = {}

    for target_date in dates_to_pull:
        try:
            day_orders = _fetch_orders_for_day(target_date)
            all_orders.extend(day_orders)
            day_daily  = _aggregate_daily(day_orders)
            all_daily.update(day_daily)
            if target_date in day_daily:
                m = day_daily[target_date]
                logger.info(
                    "  %s | orders=%d | revenue=%.2f | refunds=%.2f",
                    target_date, m["order_count"], m["revenue"], m["refunds"],
                )
            else:
                logger.info("  %s | orders=0", target_date)
        except Exception as exc:
            logger.exception("  FAILED for date %s: %s", target_date, exc)

    # Write to P&L sheet
    sheet_rows = 0
    if all_daily:
        try:
            sheet_rows = _write_daily_to_sheet(all_daily, store_id)
        except Exception as exc:
            logger.exception("Sheet write failed: %s", exc)

    # Store raw orders in PostgreSQL
    db_rows = 0
    try:
        db_rows = _store_raw_orders(all_orders)
    except Exception as exc:
        logger.exception("DB store failed: %s", exc)

    duration_ms = int((time.monotonic() - t0) * 1000)

    # Summary
    total_revenue = sum(m["revenue"] for m in all_daily.values())
    total_refunds = sum(m["refunds"] for m in all_daily.values())
    total_orders  = len(all_orders)

    logger.info(
        "Shopify pull DONE | orders=%d | revenue=%.2f | refunds=%.2f | "
        "sheet_rows=%d | db_rows=%d | duration=%dms",
        total_orders, total_revenue, total_refunds,
        sheet_rows, db_rows, duration_ms,
    )

    _log_agent_run("success", duration_ms, rows_processed=total_orders)

    return {
        "orders":        total_orders,
        "revenue":       round(total_revenue, 2),
        "refunds":       round(total_refunds, 2),
        "sheet_rows":    sheet_rows,
        "db_rows":       db_rows,
        "duration_ms":   duration_ms,
    }
