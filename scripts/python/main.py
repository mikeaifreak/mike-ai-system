"""
main.py — Finance Controller AI System orchestrator.

Usage:
    python main.py --mode pull_shopify       # pull revenue + refunds → write to P&L sheet
    python main.py --mode pull_google_ads    # pull ad spend → write adspend_google(D) to sheet
    python main.py --mode pull_pinterest_ads # pull Pinterest spend → write adspend_pinterest(E)
    python main.py --mode sync_only          # read full P&L sheet → store in PostgreSQL
    python main.py --mode morning_report     # sync + Slack daily report
    python main.py --mode read_invoices      # lightweight sheet sync, no notifications
    python main.py --mode eod_report         # WhatsApp EOD summary
    python main.py --mode reconcile          # sheet vs DB row-count check

Daily pipeline (automated by scheduler.py, all times Europe/Amsterdam):
    06:40  pull_shopify       → writes revenue(B) + refunds(O) to P&L sheet
    06:45  pull_google_ads    → writes adspend_google(D) to P&L sheet
    06:46  pull_pinterest_ads → writes adspend_pinterest(E) to P&L sheet
    06:50  sync_only          → reads full P&L row (incl. calculated cols), stores in PostgreSQL
    07:00  morning_report     → Slack report from PostgreSQL

MODE can also be set via the MODE environment variable.
"""

import argparse
import logging
import os
import sys
import time
from datetime import date, timedelta

import psycopg2

import config
from sheets_parser import fetch_pl_data
from pl_processor import process_and_store
from slack_reporter import send_daily_report, send_anomaly_alert
from whatsapp_alerts import send_eod_summary
from google_ads_puller import pull_all_stores as _pull_google_ads_stores
from pinterest_ads_puller import pull_all_stores as _pull_pinterest_ads_stores
import shopify_puller

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("finance_ai.main")


# ---------------------------------------------------------------------------
# Pipeline modes
# ---------------------------------------------------------------------------

def _sync_sheets_to_db(store_id: str = "default", url: str | None = None) -> dict:
    """Fetch from Google Sheets and upsert into PostgreSQL.

    Args:
        store_id: Shopify store identifier passed through to the DB upsert.
                  Multi-store: iterate config.GOOGLE_STORE_URLS.items() and
                  call this once per store with the matching (store_id, url).
        url:      Apps Script URL override. Defaults to config.GOOGLE_SCRIPT_URL.
    """
    logger.info("=== SYNC: Fetching P&L data | store_id=%s ===", store_id)
    rows = fetch_pl_data(store_id=store_id, url=url)
    logger.info("Fetched %d rows from sheet.", len(rows))

    logger.info("=== SYNC: Processing and storing rows ===")
    result = process_and_store(rows, store_id=store_id)
    logger.info(
        "Stored: %d inserted, %d updated, %d anomalies.",
        result["rows_inserted"],
        result["rows_updated"],
        len(result["anomalies_found"]),
    )
    return result


def run_morning_report() -> None:
    """Full morning pipeline: sync sheet → store → Slack daily report."""
    logger.info(">>> MODE: morning_report")

    result = _sync_sheets_to_db()

    # Fire anomaly Slack alerts for any flagged metrics
    for anomaly in result["anomalies_found"]:
        logger.info("Sending anomaly alert: %s", anomaly["message"])
        send_anomaly_alert(
            metric    = anomaly["metric"],
            value     = anomaly["value"],
            threshold = anomaly["threshold"],
            message   = anomaly["message"],
        )

    yesterday = date.today() - timedelta(days=1)
    logger.info("=== REPORT: Sending Slack daily report for %s ===", yesterday)
    delivered = send_daily_report(yesterday)
    logger.info("Slack report delivered: %s", delivered)


def run_pull_shopify() -> None:
    """Pull revenue + refunds from Shopify (7-day lookback) → write to P&L sheet (B, O)."""
    logger.info(">>> MODE: pull_shopify")
    result = shopify_puller.run()
    if result:
        logger.info(
            "Shopify result: orders=%d  revenue=%.2f  refunds=%.2f",
            result.get("orders", 0),
            result.get("revenue", 0.0),
            result.get("refunds", 0.0),
        )


def run_pull_google_ads() -> None:
    """Pull Google Ads spend → write adspend_google(D) to P&L sheet."""
    logger.info(">>> MODE: pull_google_ads")
    _pull_google_ads_stores()


def run_pull_pinterest_ads() -> None:
    """Pull Pinterest Ads spend → write adspend_pinterest(E) to P&L sheet."""
    logger.info(">>> MODE: pull_pinterest_ads")
    _pull_pinterest_ads_stores()


def run_sync_only() -> None:
    """Fetch + store only — no Slack/WhatsApp output."""
    logger.info(">>> MODE: sync_only")
    _sync_sheets_to_db()


def run_read_invoices() -> None:
    """Lightweight invoice/sheet sync every 30 min — no notifications."""
    logger.info(">>> MODE: read_invoices")
    _sync_sheets_to_db()


def run_eod_report() -> None:
    """Send EOD WhatsApp summary to Mike."""
    logger.info(">>> MODE: eod_report")
    delivered = send_eod_summary()
    logger.info("EOD WhatsApp delivered: %s", delivered)


def run_reconcile() -> None:
    """
    Compare sheet row count vs DB row count.
    Logs the result to reconciliation_log and prints a summary.
    """
    logger.info(">>> MODE: reconcile")

    # Sheet count
    rows = fetch_pl_data()
    sheet_count = len(rows)

    # DB count and mismatch detection
    mismatches = 0
    sheet_dates = {r["report_date"] for r in rows if r.get("report_date")}

    with psycopg2.connect(config.POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM daily_pl")
            db_count = cur.fetchone()[0]

            cur.execute("SELECT report_date FROM daily_pl")
            db_dates = {row[0] for row in cur.fetchall()}

            only_in_sheet = sheet_dates - db_dates
            only_in_db    = db_dates - sheet_dates
            mismatches = len(only_in_sheet) + len(only_in_db)

            if only_in_sheet:
                logger.warning("Dates in sheet but not DB: %s", sorted(only_in_sheet)[:10])
            if only_in_db:
                logger.warning("Dates in DB but not sheet: %s", sorted(only_in_db)[:10])

            status = "ok" if mismatches == 0 else "warning"
            notes  = (
                f"Sheet dates not in DB: {sorted(only_in_sheet)[:5]}; "
                f"DB dates not in sheet: {sorted(only_in_db)[:5]}"
                if mismatches > 0 else "Full match."
            )

            cur.execute("""
                INSERT INTO reconciliation_log (
                    run_date, sheet_row_count, db_row_count,
                    mismatches, status, notes, agent_name, model_used
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                date.today(), sheet_count, db_count,
                mismatches, status, notes,
                "reconcile_agent", config.CLAUDE_MODEL,
            ))
            conn.commit()

    logger.info(
        "Reconciliation complete: sheet=%d, db=%d, mismatches=%d, status=%s",
        sheet_count, db_count, mismatches, status,
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

MODES = {
    "pull_shopify":       run_pull_shopify,
    "pull_google_ads":    run_pull_google_ads,
    "pull_pinterest_ads": run_pull_pinterest_ads,
    "morning_report":     run_morning_report,
    "sync_only":          run_sync_only,
    "read_invoices":      run_read_invoices,
    "eod_report":         run_eod_report,
    "reconcile":          run_reconcile,
}


def run_mode(mode: str) -> None:
    """Dispatch to the correct pipeline function by mode name. Used by scheduler.py."""
    if mode not in MODES:
        raise ValueError(f"Unknown mode: {mode!r}. Valid: {list(MODES)}")
    MODES[mode]()


def main() -> None:
    parser = argparse.ArgumentParser(description="Finance Controller AI — Pipeline Runner")
    parser.add_argument(
        "--mode",
        default=os.getenv("MODE", "morning_report"),
        choices=list(MODES.keys()),
        help="Pipeline mode to run (default: morning_report)",
    )
    args = parser.parse_args()

    t_start = time.monotonic()
    logger.info(
        "============================================================\n"
        "  Finance Controller AI — START  |  mode=%s  |  %s\n"
        "============================================================",
        args.mode,
        date.today(),
    )

    try:
        MODES[args.mode]()
        status = "SUCCESS"
    except Exception as exc:
        logger.exception("Pipeline failed in mode '%s': %s", args.mode, exc)
        status = "ERROR"
        sys.exit(1)
    finally:
        elapsed = time.monotonic() - t_start
        logger.info(
            "============================================================\n"
            "  Finance Controller AI — %s  |  duration=%.2fs\n"
            "============================================================",
            status,
            elapsed,
        )


if __name__ == "__main__":
    main()
