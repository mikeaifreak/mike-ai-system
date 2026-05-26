"""
slack_reporter.py — Sends formatted Slack Block Kit messages for daily P&L
reports and mid-day anomaly alerts.
"""

import logging
from datetime import date, timedelta
from typing import Optional

import psycopg2
import psycopg2.extras
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

import config

logger = logging.getLogger(__name__)

_slack_client: Optional[WebClient] = None


def _get_client() -> WebClient:
    global _slack_client
    if _slack_client is None:
        _slack_client = WebClient(token=config.SLACK_BOT_TOKEN)
    return _slack_client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_currency(val) -> str:
    if val is None:
        return "N/A"
    return f"${val:,.2f}"


def _fmt_pct(val) -> str:
    if val is None:
        return "N/A"
    return f"{val:.1f}%"


def _fmt_roas(val) -> str:
    if val is None:
        return "N/A"
    return f"{val:.2f}x"


def _log_alert(
    cursor,
    alert_type: str,
    channel: str,
    recipient: str,
    delivered: bool,
    trigger_metric: Optional[str] = None,
    trigger_value: Optional[float] = None,
    threshold_value: Optional[float] = None,
    message_preview: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    cursor.execute("""
        INSERT INTO alerts_log (
            alert_type, channel, recipient,
            trigger_metric, trigger_value, threshold_value,
            message_preview, delivered, error_message
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        alert_type, channel, recipient,
        trigger_metric, trigger_value, threshold_value,
        message_preview, delivered, error_message,
    ))


def _fetch_daily_row(cursor, report_date: date) -> Optional[dict]:
    cursor.execute(
        "SELECT * FROM daily_pl WHERE report_date = %s",
        (report_date,),
    )
    return cursor.fetchone()


def _fetch_mtd(cursor) -> Optional[dict]:
    cursor.execute("SELECT * FROM mtd_summary")
    return cursor.fetchone()


# ---------------------------------------------------------------------------
# Block Kit builders
# ---------------------------------------------------------------------------

def _build_daily_report_blocks(
    report_date: date,
    day: dict,
    mtd: dict,
    anomalies: list[str],
) -> list[dict]:
    anomaly_text = "\n".join(f"• {a}" for a in anomalies) if anomalies else "None"

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"Daily P&L Report — {report_date.strftime('%A, %d %b %Y')}",
                "emoji": True,
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Yesterday*",
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Revenue*\n{_fmt_currency(day.get('revenue'))}"},
                {"type": "mrkdwn", "text": f"*Profit*\n{_fmt_currency(day.get('profit'))} ({_fmt_pct(day.get('profit_pct'))})"},
                {"type": "mrkdwn", "text": f"*ROAS*\n{_fmt_roas(day.get('roas'))}"},
                {"type": "mrkdwn", "text": f"*Ad Spend (Google)*\n{_fmt_currency(day.get('adspend_google'))}"},
                {"type": "mrkdwn", "text": f"*Refunds*\n{_fmt_currency(day.get('refunds'))} ({_fmt_pct(day.get('refund_pct'))})"},
                {"type": "mrkdwn", "text": f"*COG*\n{_fmt_currency(day.get('cog'))}"},
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Month-to-Date*",
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Revenue*\n{_fmt_currency(mtd.get('total_revenue') if mtd else None)}"},
                {"type": "mrkdwn", "text": f"*Profit*\n{_fmt_currency(mtd.get('total_profit') if mtd else None)}"},
                {"type": "mrkdwn", "text": f"*Avg ROAS*\n{_fmt_roas(mtd.get('avg_roas') if mtd else None)}"},
                {"type": "mrkdwn", "text": f"*Total Ad Spend*\n{_fmt_currency(mtd.get('total_adspend_google') if mtd else None)}"},
                {"type": "mrkdwn", "text": f"*Profit %*\n{_fmt_pct(mtd.get('profit_pct') if mtd else None)}"},
                {"type": "mrkdwn", "text": f"*Total Refunds*\n{_fmt_currency(mtd.get('total_refunds') if mtd else None)}"},
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":warning: *Alerts*\n{anomaly_text}",
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"_Finance Controller AI — synced from Google Sheets — {report_date}_",
                }
            ],
        },
    ]
    return blocks


def _build_anomaly_blocks(metric: str, value: float, threshold: float, message: str) -> list[dict]:
    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": ":rotating_light: Finance Anomaly Detected",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Metric*\n{metric}"},
                {"type": "mrkdwn", "text": f"*Value*\n{value}"},
                {"type": "mrkdwn", "text": f"*Threshold*\n{threshold}"},
            ],
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f":memo: {message}"},
        },
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def send_daily_report(report_date: Optional[date] = None) -> bool:
    """
    Query daily_pl for yesterday (or given date) + mtd_summary, then post
    a Block Kit report to SLACK_CHANNEL_ID.

    Returns True if message was delivered successfully.
    """
    if report_date is None:
        report_date = date.today() - timedelta(days=1)

    delivered = False
    error_msg = None

    try:
        with psycopg2.connect(config.POSTGRES_URL) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                day_row = _fetch_daily_row(cur, report_date)
                mtd_row = _fetch_mtd(cur)

                if day_row is None:
                    logger.warning("No daily_pl row found for %s — skipping Slack report.", report_date)
                    _log_alert(
                        cur,
                        alert_type    = "daily_report",
                        channel       = "slack",
                        recipient     = config.SLACK_CHANNEL_ID,
                        delivered     = False,
                        message_preview = f"No data for {report_date}",
                        error_message = "Missing row in daily_pl",
                    )
                    conn.commit()
                    return False

                # Collect anomaly strings from today's row
                anomalies = []
                roas = day_row.get("roas")
                if roas is not None and roas < config.THRESHOLD_ROAS_LOW:
                    anomalies.append(f"Low ROAS: {roas:.2f}x (threshold {config.THRESHOLD_ROAS_LOW}x)")
                ref_pct = day_row.get("refund_pct")
                if ref_pct is not None and ref_pct > config.THRESHOLD_REFUND_PCT_HIGH:
                    anomalies.append(f"High refund rate: {ref_pct:.1f}% (threshold {config.THRESHOLD_REFUND_PCT_HIGH}%)")
                p_pct = day_row.get("profit_pct")
                if p_pct is not None and p_pct < 0:
                    anomalies.append(f"Negative profit margin: {p_pct:.1f}%")

                blocks = _build_daily_report_blocks(report_date, day_row, mtd_row, anomalies)

                client = _get_client()
                response = client.chat_postMessage(
                    channel=config.SLACK_CHANNEL_ID,
                    blocks=blocks,
                    text=f"Daily P&L Report — {report_date}",  # fallback text
                )
                delivered = response["ok"]

                preview = f"Daily P&L {report_date} | Revenue: {_fmt_currency(day_row.get('revenue'))}"
                _log_alert(
                    cur,
                    alert_type     = "daily_report",
                    channel        = "slack",
                    recipient      = config.SLACK_CHANNEL_ID,
                    delivered      = delivered,
                    message_preview= preview,
                )
                conn.commit()

    except SlackApiError as exc:
        error_msg = str(exc.response["error"])
        logger.error("Slack API error in send_daily_report: %s", error_msg)
        _persist_failed_alert("daily_report", error_msg)
    except Exception as exc:
        error_msg = str(exc)
        logger.exception("send_daily_report failed: %s", exc)
        _persist_failed_alert("daily_report", error_msg)

    return delivered


def send_anomaly_alert(metric: str, value: float, threshold: float, message: str) -> bool:
    """Send an immediate Slack alert when an anomaly is detected mid-day."""
    delivered = False
    error_msg = None

    try:
        blocks = _build_anomaly_blocks(metric, value, threshold, message)
        client = _get_client()
        response = client.chat_postMessage(
            channel=config.SLACK_CHANNEL_ID,
            blocks=blocks,
            text=f"Finance Anomaly: {metric} = {value}",
        )
        delivered = response["ok"]

        with psycopg2.connect(config.POSTGRES_URL) as conn:
            with conn.cursor() as cur:
                _log_alert(
                    cur,
                    alert_type     = "anomaly",
                    channel        = "slack",
                    recipient      = config.SLACK_CHANNEL_ID,
                    delivered      = delivered,
                    trigger_metric = metric,
                    trigger_value  = value,
                    threshold_value= threshold,
                    message_preview= message[:500],
                )
                conn.commit()

    except SlackApiError as exc:
        error_msg = str(exc.response["error"])
        logger.error("Slack API error in send_anomaly_alert: %s", error_msg)
    except Exception as exc:
        error_msg = str(exc)
        logger.exception("send_anomaly_alert failed: %s", exc)

    return delivered


def _persist_failed_alert(alert_type: str, error_msg: str) -> None:
    """Best-effort persistence of a failed alert to alerts_log."""
    try:
        with psycopg2.connect(config.POSTGRES_URL) as conn:
            with conn.cursor() as cur:
                _log_alert(
                    cur,
                    alert_type   = alert_type,
                    channel      = "slack",
                    recipient    = config.SLACK_CHANNEL_ID,
                    delivered    = False,
                    error_message= error_msg,
                )
                conn.commit()
    except Exception:
        pass
