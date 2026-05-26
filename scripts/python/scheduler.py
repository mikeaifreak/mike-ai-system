"""
scheduler.py — APScheduler-based job runner replacing n8n.

Schedule (all times in TZ set by SCHEDULER_TIMEZONE env var, default UTC):
  00:00  reconcile        sheet vs DB row-count check
  06:55  sync_only        pre-fetch before morning report
  07:00  morning_report   fetch + process + Slack report
  */30   read_invoices    lightweight invoice sync every 30 minutes
  21:00  eod_report       WhatsApp EOD summary

Run:
  python scheduler.py
"""

import logging
import os
import subprocess
import sys

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("scheduler")

PYTHON = sys.executable
SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
TIMEZONE = os.getenv("SCHEDULER_TIMEZONE", "UTC")


def run_mode(mode: str) -> None:
    logger.info("Firing job: mode=%s", mode)
    result = subprocess.run([PYTHON, SCRIPT, "--mode", mode])
    if result.returncode != 0:
        logger.error("Job mode=%s exited with code %d", mode, result.returncode)
    else:
        logger.info("Job mode=%s completed OK", mode)


def main() -> None:
    scheduler = BlockingScheduler(timezone=TIMEZONE)

    scheduler.add_job(
        run_mode,
        CronTrigger(hour=0, minute=0, timezone=TIMEZONE),
        args=["reconcile"],
        id="reconcile",
        name="Daily sheet-vs-DB reconciliation (midnight)",
    )

    scheduler.add_job(
        run_mode,
        CronTrigger(hour=6, minute=55, timezone=TIMEZONE),
        args=["sync_only"],
        id="sync_only",
        name="Pre-fetch sync before morning report (06:55)",
    )

    scheduler.add_job(
        run_mode,
        CronTrigger(hour=7, minute=0, timezone=TIMEZONE),
        args=["morning_report"],
        id="morning_report",
        name="Daily morning P&L report (07:00)",
    )

    scheduler.add_job(
        run_mode,
        CronTrigger(minute="*/30", timezone=TIMEZONE),
        args=["read_invoices"],
        id="read_invoices",
        name="Invoice sync every 30 minutes",
    )

    scheduler.add_job(
        run_mode,
        CronTrigger(hour=21, minute=0, timezone=TIMEZONE),
        args=["eod_report"],
        id="eod_report",
        name="End-of-day WhatsApp summary (21:00)",
    )

    logger.info(
        "Scheduler started | timezone=%s | jobs=%d",
        TIMEZONE,
        len(scheduler.get_jobs()),
    )
    for job in scheduler.get_jobs():
        logger.info("  %-20s  next_run=%s", job.id, job.next_run_time)

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
