"""
pl_processor.py — Upserts P&L rows into PostgreSQL and detects anomalies.
"""

import logging
import time
from datetime import date, timedelta
from typing import Optional

import psycopg2
import psycopg2.extras

import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Anomaly detection thresholds (loaded from config so they're env-overridable)
# ---------------------------------------------------------------------------
ROAS_LOW_THRESHOLD       = config.THRESHOLD_ROAS_LOW          # default 1.5
REFUND_PCT_HIGH_THRESHOLD = config.THRESHOLD_REFUND_PCT_HIGH  # default 10.0

UPSERT_SQL = """
INSERT INTO daily_pl (
    store_id, report_date, revenue, cog, adspend_google, mediabuying,
    employee_cost, transaction_fee, profit, roas, profit_pct,
    cog_pct, cvr_pct, cpc, refunds, refund_pct, source, synced_at
) VALUES (
    %(store_id)s, %(report_date)s, %(revenue)s, %(cog)s, %(adspend_google)s, %(mediabuying)s,
    %(employee_cost)s, %(transaction_fee)s, %(profit)s, %(roas)s, %(profit_pct)s,
    %(cog_pct)s, %(cvr_pct)s, %(cpc)s, %(refunds)s, %(refund_pct)s,
    %(source)s, NOW()
)
ON CONFLICT (store_id, report_date) DO UPDATE SET
    revenue         = EXCLUDED.revenue,
    cog             = EXCLUDED.cog,
    adspend_google  = EXCLUDED.adspend_google,
    mediabuying     = EXCLUDED.mediabuying,
    employee_cost   = EXCLUDED.employee_cost,
    transaction_fee = EXCLUDED.transaction_fee,
    profit          = EXCLUDED.profit,
    roas            = EXCLUDED.roas,
    profit_pct      = EXCLUDED.profit_pct,
    cog_pct         = EXCLUDED.cog_pct,
    cvr_pct         = EXCLUDED.cvr_pct,
    cpc             = EXCLUDED.cpc,
    refunds         = EXCLUDED.refunds,
    refund_pct      = EXCLUDED.refund_pct,
    source          = EXCLUDED.source,
    synced_at       = NOW(),
    updated_at      = NOW()
RETURNING (xmax = 0) AS inserted;
"""


def _detect_anomalies(row: dict) -> list[dict]:
    anomalies = []
    rdate = row.get("report_date")

    roas = row.get("roas")
    if roas is not None and roas < ROAS_LOW_THRESHOLD:
        anomalies.append({
            "date":      rdate,
            "metric":    "roas",
            "value":     roas,
            "threshold": ROAS_LOW_THRESHOLD,
            "message":   f"Low ROAS {roas:.2f} on {rdate} (threshold: {ROAS_LOW_THRESHOLD})",
        })

    refund_pct = row.get("refund_pct")
    if refund_pct is not None and refund_pct > REFUND_PCT_HIGH_THRESHOLD:
        anomalies.append({
            "date":      rdate,
            "metric":    "refund_pct",
            "value":     refund_pct,
            "threshold": REFUND_PCT_HIGH_THRESHOLD,
            "message":   f"High refund rate {refund_pct:.1f}% on {rdate} (threshold: {REFUND_PCT_HIGH_THRESHOLD}%)",
        })

    profit_pct = row.get("profit_pct")
    if profit_pct is not None and profit_pct < 0:
        anomalies.append({
            "date":      rdate,
            "metric":    "profit_pct",
            "value":     profit_pct,
            "threshold": 0,
            "message":   f"Negative profit margin {profit_pct:.1f}% on {rdate}",
        })

    return anomalies


def _recalculate_weekly_summary(cursor, target_date: date) -> None:
    cursor.execute("""
        INSERT INTO weekly_summary (
            week_start, week_end, iso_year, iso_week,
            total_revenue, total_cog, total_adspend, total_mediabuying,
            total_employee, total_transaction_fee, total_profit,
            avg_roas, avg_profit_pct, avg_cog_pct, avg_cvr_pct, avg_cpc,
            total_refunds, avg_refund_pct, days_in_week, calculated_at
        )
        SELECT
            DATE_TRUNC('week', report_date)::DATE,
            (DATE_TRUNC('week', report_date) + INTERVAL '6 days')::DATE,
            EXTRACT(ISOYEAR FROM report_date)::INTEGER,
            EXTRACT(WEEK FROM report_date)::INTEGER,
            SUM(revenue), SUM(cog), SUM(adspend_google), SUM(mediabuying),
            SUM(employee_cost), SUM(transaction_fee), SUM(profit),
            AVG(roas), AVG(profit_pct), AVG(cog_pct), AVG(cvr_pct), AVG(cpc),
            SUM(refunds), AVG(refund_pct), COUNT(*), NOW()
        FROM daily_pl
        WHERE DATE_TRUNC('week', report_date) = DATE_TRUNC('week', %s::DATE)
        GROUP BY DATE_TRUNC('week', report_date)
        ON CONFLICT (iso_year, iso_week) DO UPDATE SET
            total_revenue       = EXCLUDED.total_revenue,
            total_cog           = EXCLUDED.total_cog,
            total_adspend       = EXCLUDED.total_adspend,
            total_mediabuying   = EXCLUDED.total_mediabuying,
            total_employee      = EXCLUDED.total_employee,
            total_transaction_fee = EXCLUDED.total_transaction_fee,
            total_profit        = EXCLUDED.total_profit,
            avg_roas            = EXCLUDED.avg_roas,
            avg_profit_pct      = EXCLUDED.avg_profit_pct,
            avg_cog_pct         = EXCLUDED.avg_cog_pct,
            avg_cvr_pct         = EXCLUDED.avg_cvr_pct,
            avg_cpc             = EXCLUDED.avg_cpc,
            total_refunds       = EXCLUDED.total_refunds,
            avg_refund_pct      = EXCLUDED.avg_refund_pct,
            days_in_week        = EXCLUDED.days_in_week,
            calculated_at       = NOW();
    """, (target_date,))


def _recalculate_monthly_summary(cursor, target_date: date) -> None:
    cursor.execute("""
        INSERT INTO monthly_summary (
            year, month, month_start, month_end,
            total_revenue, total_cog, total_adspend, total_mediabuying,
            total_employee, total_transaction_fee, total_profit,
            avg_roas, avg_profit_pct, avg_cog_pct, avg_cvr_pct, avg_cpc,
            total_refunds, avg_refund_pct, days_in_month, calculated_at
        )
        SELECT
            EXTRACT(YEAR FROM report_date)::INTEGER,
            EXTRACT(MONTH FROM report_date)::INTEGER,
            DATE_TRUNC('month', report_date)::DATE,
            (DATE_TRUNC('month', report_date) + INTERVAL '1 month' - INTERVAL '1 day')::DATE,
            SUM(revenue), SUM(cog), SUM(adspend_google), SUM(mediabuying),
            SUM(employee_cost), SUM(transaction_fee), SUM(profit),
            AVG(roas), AVG(profit_pct), AVG(cog_pct), AVG(cvr_pct), AVG(cpc),
            SUM(refunds), AVG(refund_pct), COUNT(*), NOW()
        FROM daily_pl
        WHERE DATE_TRUNC('month', report_date) = DATE_TRUNC('month', %s::DATE)
        GROUP BY DATE_TRUNC('month', report_date)
        ON CONFLICT (year, month) DO UPDATE SET
            total_revenue       = EXCLUDED.total_revenue,
            total_cog           = EXCLUDED.total_cog,
            total_adspend       = EXCLUDED.total_adspend,
            total_mediabuying   = EXCLUDED.total_mediabuying,
            total_employee      = EXCLUDED.total_employee,
            total_transaction_fee = EXCLUDED.total_transaction_fee,
            total_profit        = EXCLUDED.total_profit,
            avg_roas            = EXCLUDED.avg_roas,
            avg_profit_pct      = EXCLUDED.avg_profit_pct,
            avg_cog_pct         = EXCLUDED.avg_cog_pct,
            avg_cvr_pct         = EXCLUDED.avg_cvr_pct,
            avg_cpc             = EXCLUDED.avg_cpc,
            total_refunds       = EXCLUDED.total_refunds,
            avg_refund_pct      = EXCLUDED.avg_refund_pct,
            days_in_month       = EXCLUDED.days_in_month,
            calculated_at       = NOW();
    """, (target_date,))


def _log_agent_run(
    cursor,
    agent_name: str,
    status: str,
    rows_processed: int = 0,
    rows_inserted: int = 0,
    rows_updated: int = 0,
    duration_ms: Optional[int] = None,
    error_message: Optional[str] = None,
) -> None:
    cursor.execute("""
        INSERT INTO agent_runs (
            agent_name, workflow_name, trigger_type, status,
            rows_processed, rows_inserted, rows_updated,
            duration_ms, error_message, model, finished_at
        ) VALUES (
            %s, 'finance_pl_pipeline', 'scheduled', %s,
            %s, %s, %s,
            %s, %s, %s, NOW()
        )
    """, (
        agent_name, status,
        rows_processed, rows_inserted, rows_updated,
        duration_ms, error_message, config.CLAUDE_MODEL,
    ))


def process_and_store(rows: list[dict], store_id: str = "default") -> dict:
    """
    Upsert P&L rows into PostgreSQL.

    Args:
        rows:     List of row dicts from sheets_parser.fetch_pl_data().
                  Each dict may already contain a 'store_id' key (set by the
                  parser). The store_id parameter here takes precedence,
                  ensuring all rows in one batch share the same store identity.
        store_id: Shopify store identifier. Defaults to 'default' (single-store
                  mode). Multi-store callers pass the per-store ID so the
                  ON CONFLICT (store_id, report_date) key resolves correctly.

    Returns:
        {
          "rows_inserted": int,
          "rows_updated":  int,
          "anomalies_found": [{"date", "metric", "value", "threshold", "message"}],
        }
    """
    t_start = time.monotonic()
    rows_inserted = 0
    rows_updated  = 0
    all_anomalies = []
    cutoff_date   = date.today() - timedelta(days=config.REPROCESS_WINDOW_DAYS)

    # Weeks/months we need to recalculate after upsert
    affected_weeks  = set()
    affected_months = set()

    try:
        with psycopg2.connect(config.POSTGRES_URL) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                for row in rows:
                    rdate = row.get("report_date")
                    if rdate is None:
                        continue

                    # Only process rows within the reprocessing window or newer
                    # (older historical rows are still inserted on first sync)
                    params = {
                        "store_id":       store_id,
                        "report_date":    rdate,
                        "revenue":        row.get("revenue"),
                        "cog":            row.get("cog"),
                        "adspend_google": row.get("adspend_google"),
                        "mediabuying":    row.get("mediabuying"),
                        "employee_cost":  row.get("employee_cost"),
                        "transaction_fee":row.get("transaction_fee"),
                        "profit":         row.get("profit"),
                        "roas":           row.get("roas"),
                        "profit_pct":     row.get("profit_pct"),
                        "cog_pct":        row.get("cog_pct"),
                        "cvr_pct":        row.get("cvr_pct"),
                        "cpc":            row.get("cpc"),
                        "refunds":        row.get("refunds"),
                        "refund_pct":     row.get("refund_pct"),
                        "source":         "google_sheets",
                    }

                    cur.execute(UPSERT_SQL, params)
                    result = cur.fetchone()
                    if result and result["inserted"]:
                        rows_inserted += 1
                    else:
                        rows_updated += 1

                    affected_weeks.add(rdate)
                    affected_months.add(rdate)

                    # Only flag anomalies for recent data (last 7 days)
                    if rdate >= cutoff_date:
                        all_anomalies.extend(_detect_anomalies(row))

                # Recalculate summaries for all affected periods
                for d in affected_weeks:
                    _recalculate_weekly_summary(cur, d)
                for d in affected_months:
                    _recalculate_monthly_summary(cur, d)

                duration_ms = int((time.monotonic() - t_start) * 1000)
                _log_agent_run(
                    cur,
                    agent_name    = "pl_processor",
                    status        = "success",
                    rows_processed= len(rows),
                    rows_inserted = rows_inserted,
                    rows_updated  = rows_updated,
                    duration_ms   = duration_ms,
                )
                conn.commit()

    except Exception as exc:
        duration_ms = int((time.monotonic() - t_start) * 1000)
        logger.exception("process_and_store failed: %s", exc)
        # Best-effort error log (new connection since current one may be broken)
        try:
            with psycopg2.connect(config.POSTGRES_URL) as conn2:
                with conn2.cursor() as cur2:
                    _log_agent_run(
                        cur2,
                        agent_name    = "pl_processor",
                        status        = "error",
                        duration_ms   = duration_ms,
                        error_message = str(exc),
                    )
                    conn2.commit()
        except Exception:
            pass
        raise

    logger.info(
        "process_and_store done: %d inserted, %d updated, %d anomalies.",
        rows_inserted, rows_updated, len(all_anomalies),
    )
    return {
        "rows_inserted":  rows_inserted,
        "rows_updated":   rows_updated,
        "anomalies_found": all_anomalies,
    }
