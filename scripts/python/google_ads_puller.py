"""
google_ads_puller.py — Pulls daily ad spend from Google Ads API.

Fetches metrics for yesterday across all non-removed campaigns per customer,
aggregates to a single daily total, converts cost_micros → dollars, and
upserts adspend_google + cpc + cvr_pct into daily_pl.

Source of truth for ad spend: Google Ads API (not Google Sheets).
The sheet sync (06:50) fills in revenue, COG, etc. but does NOT overwrite
adspend_google if already populated by this puller — see pl_processor.py
which uses COALESCE for those columns.

Pipeline position:
  06:45  pull_google_ads  ← this module
  06:50  sync_only        ← sheets_parser.py fills remaining P&L columns
  07:00  morning_report   ← full data available

Multi-store:
  GOOGLE_ADS_CUSTOMER_IDS=123456789              → single store  ('default')
  GOOGLE_ADS_CUSTOMER_IDS=store_nl:123,store_de:456 → multi-store
  Config parsed in config.py → GOOGLE_ADS_STORE_CUSTOMERS: dict[store_id, customer_id]

Credentials (all from .env, no google-ads.yaml file needed in Docker):
  GOOGLE_ADS_DEVELOPER_TOKEN
  GOOGLE_ADS_CLIENT_ID
  GOOGLE_ADS_CLIENT_SECRET
  GOOGLE_ADS_REFRESH_TOKEN
"""

import logging
import time
from datetime import date, timedelta
from typing import Optional

import psycopg2
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

import config

logger = logging.getLogger(__name__)

MICROS = 1_000_000

# Fetch per-campaign metrics for the target date, then aggregate in Python.
# Filtering REMOVED campaigns avoids pulling deleted campaigns with zero spend.
GAQL = """
    SELECT
        segments.date,
        metrics.cost_micros,
        metrics.impressions,
        metrics.clicks,
        metrics.conversions
    FROM campaign
    WHERE segments.date = '{date}'
      AND campaign.status != 'REMOVED'
"""

# Only update the ad spend columns on conflict — revenue, COG etc. are owned
# by the sheet sync and must not be touched here.
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
# Google Ads client
# ---------------------------------------------------------------------------

def _build_client() -> GoogleAdsClient:
    """
    Build a GoogleAdsClient from env vars.

    The google-ads library normally reads a google-ads.yaml file, but
    load_from_dict() accepts the same keys directly — no file needed in Docker.
    """
    missing = [
        k for k in (
            "GOOGLE_ADS_DEVELOPER_TOKEN",
            "GOOGLE_ADS_CLIENT_ID",
            "GOOGLE_ADS_CLIENT_SECRET",
            "GOOGLE_ADS_REFRESH_TOKEN",
        )
        if not getattr(config, k, "")
    ]
    if missing:
        raise EnvironmentError(
            f"Google Ads credentials not set: {missing}. "
            "Add them to .env to enable the pull_google_ads pipeline."
        )

    return GoogleAdsClient.load_from_dict({
        "developer_token": config.GOOGLE_ADS_DEVELOPER_TOKEN,
        "client_id":       config.GOOGLE_ADS_CLIENT_ID,
        "client_secret":   config.GOOGLE_ADS_CLIENT_SECRET,
        "refresh_token":   config.GOOGLE_ADS_REFRESH_TOKEN,
        "use_proto_plus":  True,
    })


# ---------------------------------------------------------------------------
# Per-customer fetch
# ---------------------------------------------------------------------------

def _fetch_customer_spend(
    client: GoogleAdsClient,
    customer_id: str,
    target_date: date,
) -> Optional[dict]:
    """
    Query Google Ads for one customer's campaign totals on target_date.
    Returns a metrics dict, or None if no campaign data exists for that day.
    """
    service = client.get_service("GoogleAdsService")
    query = GAQL.format(date=target_date.strftime("%Y-%m-%d"))

    try:
        stream = service.search_stream(customer_id=customer_id, query=query)
    except GoogleAdsException as exc:
        for error in exc.failure.errors:
            logger.error(
                "Google Ads API error [customer=%s]: %s", customer_id, error.message
            )
        raise

    cost_micros = 0
    impressions = 0
    clicks      = 0
    conversions = 0.0
    rows_seen   = 0

    for batch in stream:
        for row in batch.results:
            cost_micros += row.metrics.cost_micros
            impressions += row.metrics.impressions
            clicks      += row.metrics.clicks
            conversions += row.metrics.conversions
            rows_seen   += 1

    if rows_seen == 0:
        logger.warning(
            "No campaign rows for customer_id=%s on %s — skipping upsert.",
            customer_id, target_date,
        )
        return None

    cost    = cost_micros / MICROS
    cpc     = round(cost / clicks, 4)               if clicks > 0 else None
    cvr_pct = round((conversions / clicks) * 100, 4) if clicks > 0 else None

    logger.info(
        "  [customer=%s] cost=$%.2f  clicks=%d  impr=%d  conv=%.2f"
        "  cpc=%s  cvr=%s",
        customer_id, cost, clicks, impressions, conversions,
        f"${cpc:.4f}" if cpc is not None else "—",
        f"{cvr_pct:.2f}%" if cvr_pct is not None else "—",
    )
    return {
        "cost":        cost,
        "clicks":      clicks,
        "impressions": impressions,
        "conversions": conversions,
        "cpc":         cpc,
        "cvr_pct":     cvr_pct,
    }


# ---------------------------------------------------------------------------
# DB write
# ---------------------------------------------------------------------------

def _upsert_ads_spend(store_id: str, target_date: date, metrics: dict) -> None:
    with psycopg2.connect(config.POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(UPSERT_ADS_SQL, {
                "store_id":       store_id,
                "report_date":    target_date,
                "adspend_google": metrics["cost"],
                "cpc":            metrics["cpc"],
                "cvr_pct":        metrics["cvr_pct"],
            })
            conn.commit()


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
                        "google_ads_api",
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
    Pull yesterday's ad spend for every store in config.GOOGLE_ADS_STORE_CUSTOMERS.

    Single-store:  GOOGLE_ADS_CUSTOMER_IDS=123456789
    Multi-store:   GOOGLE_ADS_CUSTOMER_IDS=store_nl:123456,store_de:789012

    Skips gracefully if GOOGLE_ADS_CUSTOMER_IDS is not set or credentials
    are missing — the rest of the pipeline continues unaffected.
    """
    if not config.GOOGLE_ADS_STORE_CUSTOMERS:
        logger.warning(
            "GOOGLE_ADS_CUSTOMER_IDS is not set — skipping Google Ads pull. "
            "Set it in .env to enable automatic ad spend sync."
        )
        return

    yesterday = date.today() - timedelta(days=1)
    logger.info(
        "Google Ads pull | date=%s | stores=%s",
        yesterday, list(config.GOOGLE_ADS_STORE_CUSTOMERS.keys()),
    )

    try:
        client = _build_client()
    except EnvironmentError as exc:
        logger.error("%s", exc)
        return

    for store_id, customer_id in config.GOOGLE_ADS_STORE_CUSTOMERS.items():
        t0 = time.monotonic()
        logger.info("Pulling store_id=%s  customer_id=%s", store_id, customer_id)
        try:
            metrics = _fetch_customer_spend(client, customer_id, yesterday)
            duration_ms = int((time.monotonic() - t0) * 1000)

            if metrics:
                _upsert_ads_spend(store_id, yesterday, metrics)
                _log_agent_run(store_id, "success", duration_ms, rows_processed=1)
            else:
                _log_agent_run(
                    store_id, "warning", duration_ms,
                    error_message="No campaign rows returned from Google Ads",
                )

        except Exception as exc:
            duration_ms = int((time.monotonic() - t0) * 1000)
            logger.exception("Google Ads pull failed [store=%s]: %s", store_id, exc)
            _log_agent_run(store_id, "error", duration_ms, error_message=str(exc))
