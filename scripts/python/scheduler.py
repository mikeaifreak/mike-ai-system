"""
scheduler.py — APScheduler job runner (replaces n8n).

Jobs (all times Europe/Amsterdam):
  00:00        reconcile           nightly sheet vs DB check
  06:40        pull_shopify        write revenue(B) + refunds(O) to P&L sheet
  06:45        pull_google_ads     write adspend_google(D) to P&L sheet
  06:46        pull_pinterest_ads  write adspend_pinterest(E) to P&L sheet
  06:50        sync_only           read full P&L row (incl. formulas), store in PostgreSQL
  07:00        morning_report      Slack daily P&L report (complete data)
  07:05        all_brands_summary  Slack all-store summary table
  08:00 Mon    weekly_report       Slack weekly P&L recap (Mondays only)
  */30         read_invoices       Poll #supplier-invoices, GPT-4o extraction
  21:00        eod_report          WhatsApp EOD summary

Every job is logged to agent_runs. Failures send a Slack alert to
SLACK_ALERTS_CHANNEL (falls back to SLACK_CHANNEL_ID).
"""

import logging
import os
import signal
import sys
import time
from typing import Optional

import psycopg2
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

load_dotenv()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("scheduler")

# ---------------------------------------------------------------------------
# Config (read directly so scheduler can start even if a pipeline var is unset)
# ---------------------------------------------------------------------------
POSTGRES_URL       = os.getenv("POSTGRES_URL", "")
SLACK_BOT_TOKEN    = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_ALERTS_CHANNEL = os.getenv("SLACK_ALERTS_CHANNEL") or os.getenv("SLACK_CHANNEL_ID", "")
TIMEZONE           = os.getenv("SCHEDULER_TIMEZONE", "Europe/Amsterdam")

# ---------------------------------------------------------------------------
# Lazy import — keeps scheduler bootable if pipeline deps are temporarily broken
# ---------------------------------------------------------------------------
def _get_run_mode():
    from main import run_mode  # noqa: PLC0415
    return run_mode


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _db_log_start(mode: str) -> Optional[str]:
    """Insert a 'running' row into agent_runs, return its UUID string."""
    if not POSTGRES_URL:
        return None
    try:
        with psycopg2.connect(POSTGRES_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agent_runs
                        (agent_name, workflow_name, trigger_type, status)
                    VALUES (%s, %s, 'cron', 'running')
                    RETURNING id::text
                    """,
                    (f"scheduler.{mode}", mode),
                )
                run_id = cur.fetchone()[0]
                conn.commit()
                return run_id
    except Exception as exc:
        logger.warning("DB log_start failed: %s", exc)
        return None


def _db_log_end(
    run_id: Optional[str],
    status: str,
    duration_ms: int,
    error_message: Optional[str] = None,
) -> None:
    """Update the agent_runs row with final status + timing."""
    if not run_id or not POSTGRES_URL:
        return
    try:
        with psycopg2.connect(POSTGRES_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE agent_runs
                    SET status        = %s,
                        finished_at   = NOW(),
                        duration_ms   = %s,
                        error_message = %s
                    WHERE id = %s::uuid
                    """,
                    (status, duration_ms, error_message, run_id),
                )
                conn.commit()
    except Exception as exc:
        logger.warning("DB log_end failed: %s", exc)


# ---------------------------------------------------------------------------
# Slack failure alert
# ---------------------------------------------------------------------------

def _slack_failure_alert(mode: str, exc: Exception) -> None:
    if not SLACK_BOT_TOKEN or not SLACK_ALERTS_CHANNEL:
        logger.warning("Slack alert skipped — SLACK_BOT_TOKEN or SLACK_ALERTS_CHANNEL not set")
        return
    try:
        client = WebClient(token=SLACK_BOT_TOKEN)
        client.chat_postMessage(
            channel=SLACK_ALERTS_CHANNEL,
            text=(
                f":rotating_light: *Scheduler job failed*\n"
                f"*Mode:* `{mode}`\n"
                f"*Error:* `{exc}`"
            ),
        )
    except SlackApiError as slack_exc:
        logger.warning("Slack failure alert error: %s", slack_exc)


# ---------------------------------------------------------------------------
# Job executor
# ---------------------------------------------------------------------------

def _execute(mode: str) -> None:
    """Run one pipeline mode, log start/end to agent_runs, alert Slack on error."""
    run_id = _db_log_start(mode)
    t0 = time.monotonic()
    logger.info("=" * 60)
    logger.info("[%s] START", mode.upper())

    try:
        run_mode = _get_run_mode()
        run_mode(mode)
        duration_ms = int((time.monotonic() - t0) * 1000)
        logger.info("[%s] OK  duration=%dms", mode.upper(), duration_ms)
        _db_log_end(run_id, "success", duration_ms)
    except Exception as exc:
        duration_ms = int((time.monotonic() - t0) * 1000)
        logger.exception("[%s] FAILED  duration=%dms  error=%s", mode.upper(), duration_ms, exc)
        _db_log_end(run_id, "error", duration_ms, str(exc))
        _slack_failure_alert(mode, exc)
    finally:
        logger.info("=" * 60)


# ---------------------------------------------------------------------------
# Scheduler setup
# ---------------------------------------------------------------------------

def main() -> None:
    scheduler = BlockingScheduler(timezone=TIMEZONE)

    scheduler.add_job(
        _execute,
        CronTrigger(hour=0, minute=0, timezone=TIMEZONE),
        args=["reconcile"],
        id="reconcile",
        name="Nightly sheet-vs-DB reconciliation (00:00)",
    )

    scheduler.add_job(
        _execute,
        CronTrigger(hour=6, minute=40, timezone=TIMEZONE),
        args=["pull_shopify"],
        id="pull_shopify",
        name="Shopify revenue + refunds → P&L sheet (06:40)",
    )

    scheduler.add_job(
        _execute,
        CronTrigger(hour=6, minute=45, timezone=TIMEZONE),
        args=["pull_google_ads"],
        id="pull_google_ads",
        name="Google Ads spend → P&L sheet col D (06:45)",
    )

    scheduler.add_job(
        _execute,
        CronTrigger(hour=6, minute=46, timezone=TIMEZONE),
        args=["pull_pinterest_ads"],
        id="pull_pinterest_ads",
        name="Pinterest Ads spend → P&L sheet col E (06:46)",
    )

    scheduler.add_job(
        _execute,
        CronTrigger(hour=6, minute=50, timezone=TIMEZONE),
        args=["sync_only"],
        id="sync_only",
        name="Read full P&L row → PostgreSQL (06:50)",
    )

    scheduler.add_job(
        _execute,
        CronTrigger(hour=7, minute=0, timezone=TIMEZONE),
        args=["morning_report"],
        id="morning_report",
        name="Daily Slack P&L report (07:00)",
    )

    scheduler.add_job(
        _execute,
        CronTrigger(hour=7, minute=5, timezone=TIMEZONE),
        args=["all_brands_summary"],
        id="all_brands_summary",
        name="All-brands Slack summary (07:05)",
    )

    scheduler.add_job(
        _execute,
        CronTrigger(day_of_week="mon", hour=8, minute=0, timezone=TIMEZONE),
        args=["weekly_report"],
        id="weekly_report",
        name="Weekly Slack P&L recap — Mon 08:00",
    )

    scheduler.add_job(
        _execute,
        CronTrigger(minute="*/30", timezone=TIMEZONE),
        args=["read_invoices"],
        id="read_invoices",
        name="Slack invoice scan via GPT-4o (every 30 min)",
    )

    scheduler.add_job(
        _execute,
        CronTrigger(hour=21, minute=0, timezone=TIMEZONE),
        args=["eod_report"],
        id="eod_report",
        name="WhatsApp EOD summary (21:00)",
    )

    # Graceful shutdown on SIGTERM / SIGINT
    def _shutdown(signum, frame):
        logger.info("Signal %d received — shutting down scheduler", signum)
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    logger.info("Scheduler starting | timezone=%s", TIMEZONE)
    logger.info("%-20s  %-45s  %s", "JOB ID", "NAME", "NEXT RUN")
    logger.info("-" * 90)
    for job in scheduler.get_jobs():
        next_run = getattr(job, "next_run_time", "pending")
        logger.info("%-20s  %-45s  %s", job.id, job.name, next_run)
    logger.info("-" * 90)

    scheduler.start()


if __name__ == "__main__":
    main()
