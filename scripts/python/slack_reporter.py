"""
slack_reporter.py — Slack Block Kit messaging for the Finance Controller AI.

Public functions:
  send_daily_report(date)          → SLACK_REPORTS_CHANNEL, one per store
  send_weekly_report()             → SLACK_REPORTS_CHANNEL, Mon 08:00
  send_all_brands_summary(date)    → SLACK_CHANNEL_ID, after daily_report
  send_anomaly_alert(...)          → SLACK_ALERTS_CHANNEL, instant
  send_invoice_confirmation(...)   → SLACK_INVOICES_CHANNEL, thread reply

All functions:
  - Use Slack Block Kit (no plain text)
  - Log to alerts_log after sending
  - Use Europe/Amsterdam timestamps
  - Never crash scheduler — catch all exceptions
"""

import logging
from datetime import date, timedelta, datetime, timezone
from typing import Optional

import psycopg2
import psycopg2.extras
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

import config

logger = logging.getLogger(__name__)

_slack_client: Optional[WebClient] = None

# Amsterdam offset (rough, avoids pytz dependency)
_AMS_OFFSET = timedelta(hours=2)  # CEST (Apr–Oct); CET (+1) is close enough for labels

STORE_DISPLAY_NAMES = {
    "default": "FRUGAZE",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_client() -> WebClient:
    global _slack_client
    if _slack_client is None:
        _slack_client = WebClient(token=config.SLACK_BOT_TOKEN)
    return _slack_client


def _store_name(store_id: str) -> str:
    return STORE_DISPLAY_NAMES.get(store_id, store_id.upper())


def _fmt_currency(val) -> str:
    if val is None:
        return "N/A"
    return f"${float(val):,.2f}"


def _fmt_compact(val) -> str:
    """Short currency — no decimals, for table columns."""
    if val is None:
        return "N/A"
    return f"${float(val):,.0f}"


def _fmt_pct(val) -> str:
    if val is None:
        return "N/A"
    return f"{float(val):.1f}%"


def _fmt_roas(val) -> str:
    if val is None:
        return "N/A"
    return f"{float(val):.2f}x"


def _pct_change(this_val, prev_val) -> Optional[float]:
    """Return % change, or None if prev_val is zero/None."""
    if prev_val is None or float(prev_val) == 0 or this_val is None:
        return None
    return (float(this_val) - float(prev_val)) / abs(float(prev_val)) * 100


def _change_str(change: Optional[float], good_if_up: bool = True) -> str:
    """Format a % change with ▲/▼ indicator."""
    if change is None:
        return "  —"
    symbol   = "▲" if change >= 0 else "▼"
    sign     = "+" if change >= 0 else ""
    return f"{sign}{change:.1f}% {symbol}"


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
        (message_preview or "")[:500], delivered, error_message,
    ))


def _persist_failed_alert(alert_type: str, channel: str, error_msg: str) -> None:
    """Best-effort: write a failed delivery row to alerts_log."""
    try:
        with psycopg2.connect(config.POSTGRES_URL) as conn:
            with conn.cursor() as cur:
                _log_alert(cur, alert_type, "slack", channel,
                           False, error_message=error_msg)
                conn.commit()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Block Kit builders
# ---------------------------------------------------------------------------

def _build_daily_blocks(
    report_date: date,
    day: dict,
    mtd: Optional[dict],
    anomalies: list[str],
    store_id: str,
) -> list[dict]:
    name = _store_name(store_id)

    ad_google    = day.get("adspend_google") or 0
    ad_pinterest = day.get("adspend_pinterest") or 0
    ad_total     = ad_google + ad_pinterest

    refund_pct = day.get("refund_pct") or 0
    profit_pct = day.get("profit_pct") or 0

    metrics_lines = (
        f"💰 *Revenue:*      {_fmt_currency(day.get('revenue'))}\n"
        f"📦 *COG:*          {_fmt_currency(day.get('cog'))}\n"
        f"📣 *Ad Spend:*     {_fmt_currency(ad_total)}\n"
        f"   ↳ Google:     {_fmt_currency(ad_google)}\n"
        f"   ↳ Pinterest:  {_fmt_currency(ad_pinterest)}\n"
        f"💸 *Refunds:*      {_fmt_currency(day.get('refunds'))} ({_fmt_pct(refund_pct)})\n"
        f"✅ *Profit:*       {_fmt_currency(day.get('profit'))} ({_fmt_pct(profit_pct)})\n"
        f"📈 *ROAS:*         {_fmt_roas(day.get('roas'))}"
    )

    if mtd:
        mtd_lines = (
            f"📅 *Month to Date*\n"
            f"   Revenue:  {_fmt_currency(mtd.get('total_revenue'))}\n"
            f"   Profit:   {_fmt_currency(mtd.get('total_profit'))}\n"
            f"   Avg ROAS: {_fmt_roas(mtd.get('avg_roas'))}"
        )
    else:
        mtd_lines = "📅 *Month to Date* — no data yet"

    if anomalies:
        alert_lines = "⚠️ *Alerts*\n" + "\n".join(f"   • {a}" for a in anomalies)
    else:
        alert_lines = "✅ *Alerts:* None — all metrics healthy"

    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"Daily P&L — {name} | {report_date.strftime('%a %d %b %Y')}",
                "emoji": True,
            },
        },
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": metrics_lines}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": mtd_lines}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": alert_lines}},
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"_Finance Controller AI · synced from Google Sheets · "
                        f"{report_date.strftime('%d %b %Y')}_"
                    ),
                }
            ],
        },
    ]


def _build_weekly_blocks(
    this_week: dict,
    prev_week: Optional[dict],
    iso_year: int,
    iso_week: int,
    prev_iso_week: Optional[int],
) -> list[dict]:
    def row(label: str, key: str, good_if_up: bool = True) -> str:
        tv = this_week.get(key)
        pv = prev_week.get(key) if prev_week else None
        chg = _pct_change(tv, pv)
        val_str = _fmt_compact(tv)
        chg_str = _change_str(chg, good_if_up)
        return f"{label:<10} {val_str:<12} {chg_str}"

    def roas_row() -> str:
        tv = this_week.get("avg_roas")
        pv = prev_week.get("avg_roas") if prev_week else None
        if tv is None:
            return f"{'Avg ROAS':<10} {'N/A':<12}"
        diff = (float(tv) - float(pv)) if pv else None
        diff_str = f"+{diff:.2f} ▲" if diff and diff >= 0 else (f"{diff:.2f} ▼" if diff else "—")
        return f"{'Avg ROAS':<10} {float(tv):.2f}x       {diff_str}"

    prev_label = f"Week {prev_iso_week}" if prev_iso_week else "No prev"
    table = (
        f"{'Metric':<10} {'This Week':<12} vs {prev_label}\n"
        f"{'─' * 42}\n"
        + row("Revenue",  "total_revenue",  good_if_up=True)  + "\n"
        + row("Profit",   "total_profit",   good_if_up=True)  + "\n"
        + row("AdSpend",  "total_adspend",  good_if_up=False) + "\n"
        + row("Refunds",  "total_refunds",  good_if_up=False) + "\n"
        + roas_row()
    )

    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"Weekly Summary — FRUGAZE | Week {iso_week}, {iso_year}",
                "emoji": True,
            },
        },
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"```\n{table}\n```"}},
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "_Finance Controller AI — weekly P&L digest_",
                }
            ],
        },
    ]


def _build_all_brands_blocks(report_date: date, store_rows: list[dict]) -> list[dict]:
    header = f"{'Store':<12} {'Revenue':>10}  {'Profit':>9}  {'ROAS':>6}"
    sep    = "─" * 44
    lines  = [header, sep]

    total_rev    = 0.0
    total_profit = 0.0

    for r in store_rows:
        sid     = r.get("store_id", "default")
        rev     = float(r.get("revenue") or 0)
        profit  = float(r.get("profit")  or 0)
        roas    = r.get("roas")
        total_rev    += rev
        total_profit += profit
        lines.append(
            f"{_store_name(sid):<12} {_fmt_compact(rev):>10}  "
            f"{_fmt_compact(profit):>9}  "
            f"{float(roas):.2f}x" if roas else f"{_store_name(sid):<12} {_fmt_compact(rev):>10}  {_fmt_compact(profit):>9}  —"
        )

    lines.append(sep)
    avg_roas_total = (
        sum(float(r.get("roas") or 0) for r in store_rows if r.get("roas"))
        / len([r for r in store_rows if r.get("roas")])
        if any(r.get("roas") for r in store_rows) else 0
    )
    lines.append(
        f"{'TOTAL':<12} {_fmt_compact(total_rev):>10}  "
        f"{_fmt_compact(total_profit):>9}  "
        f"{avg_roas_total:.2f}x"
    )

    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"All Stores Summary | {report_date.strftime('%a %d %b %Y')}",
                "emoji": True,
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "🏪 *Store Performance*"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"```\n" + "\n".join(lines) + "\n```"},
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"_Finance Controller AI — {report_date.strftime('%d %b %Y')}_",
                }
            ],
        },
    ]


def _build_anomaly_blocks(
    store: str,
    metric: str,
    value: float,
    threshold: float,
    anomaly_type: str,
    action: str,
    report_date: date,
) -> list[dict]:
    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"ANOMALY DETECTED — {_store_name(store)}",
                "emoji": True,
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Type*\n{anomaly_type}"},
                {"type": "mrkdwn", "text": f"*Metric*\n{metric}"},
                {"type": "mrkdwn", "text": f"*Value*\n{value}"},
                {"type": "mrkdwn", "text": f"*Threshold*\n{threshold}"},
                {"type": "mrkdwn", "text": f"*Date*\n{report_date}"},
                {"type": "mrkdwn", "text": f"*Action*\n{action}"},
            ],
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": "_Finance Controller AI — anomaly detector_"}
            ],
        },
    ]


# ---------------------------------------------------------------------------
# FUNCTION 1 — Daily Report
# ---------------------------------------------------------------------------

def send_daily_report(report_date: Optional[date] = None) -> bool:
    """
    Post a Block Kit daily P&L report to SLACK_REPORTS_CHANNEL.
    One message per store. Returns True if all delivered successfully.
    """
    if report_date is None:
        report_date = date.today() - timedelta(days=1)

    all_ok = True

    try:
        with psycopg2.connect(config.POSTGRES_URL) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:

                # Fetch all stores that have data for this date
                cur.execute(
                    "SELECT * FROM daily_pl WHERE report_date = %s ORDER BY store_id",
                    (report_date,),
                )
                day_rows = cur.fetchall()

                if not day_rows:
                    logger.warning("No daily_pl rows for %s — skipping Slack report.", report_date)
                    _log_alert(
                        cur, "daily_report", "slack", config.SLACK_REPORTS_CHANNEL,
                        False, message_preview=f"No data for {report_date}",
                        error_message="Missing row in daily_pl",
                    )
                    conn.commit()
                    return False

                cur.execute("SELECT * FROM mtd_summary")
                mtd_row = cur.fetchone()

                client = _get_client()

                for day_row in day_rows:
                    store_id = day_row.get("store_id", "default")

                    # Collect anomalies from this day's row
                    anomalies = []
                    roas = day_row.get("roas")
                    if roas is not None and roas < config.THRESHOLD_ROAS_LOW:
                        anomalies.append(
                            f"Low ROAS: {float(roas):.2f}x (threshold {config.THRESHOLD_ROAS_LOW}x)"
                        )
                    ref_pct = day_row.get("refund_pct")
                    if ref_pct is not None and ref_pct > config.THRESHOLD_REFUND_PCT_HIGH:
                        anomalies.append(
                            f"High refund rate: {float(ref_pct):.1f}% (threshold {config.THRESHOLD_REFUND_PCT_HIGH}%)"
                        )
                    p_pct = day_row.get("profit_pct")
                    if p_pct is not None and p_pct < 0:
                        anomalies.append(f"Negative profit margin: {float(p_pct):.1f}%")

                    blocks = _build_daily_blocks(report_date, day_row, mtd_row, anomalies, store_id)

                    delivered = False
                    error_msg = None
                    try:
                        resp = client.chat_postMessage(
                            channel=config.SLACK_REPORTS_CHANNEL,
                            blocks=blocks,
                            text=f"Daily P&L — {_store_name(store_id)} | {report_date}",
                        )
                        delivered = resp["ok"]
                    except SlackApiError as exc:
                        error_msg = str(exc.response.get("error", exc))
                        logger.error("Slack error posting daily report for %s: %s", store_id, error_msg)
                        all_ok = False

                    preview = (
                        f"Daily P&L {report_date} | {_store_name(store_id)} | "
                        f"Revenue: {_fmt_currency(day_row.get('revenue'))}"
                    )
                    _log_alert(
                        cur, "daily_report", "slack", config.SLACK_REPORTS_CHANNEL,
                        delivered, message_preview=preview, error_message=error_msg,
                    )

                conn.commit()

    except Exception as exc:
        logger.exception("send_daily_report failed: %s", exc)
        _persist_failed_alert("daily_report", config.SLACK_REPORTS_CHANNEL, str(exc))
        return False

    return all_ok


# ---------------------------------------------------------------------------
# FUNCTION 2 — Weekly Report
# ---------------------------------------------------------------------------

def send_weekly_report() -> bool:
    """
    Post this-week vs last-week P&L summary to SLACK_REPORTS_CHANNEL.
    Triggered Monday 08:00.
    """
    today = date.today()
    iso_year, iso_week, _ = today.isocalendar()
    prev_date = today - timedelta(weeks=1)
    prev_iso_year, prev_iso_week, _ = prev_date.isocalendar()

    delivered = False

    try:
        with psycopg2.connect(config.POSTGRES_URL) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:

                cur.execute(
                    "SELECT * FROM weekly_summary WHERE iso_year = %s AND iso_week = %s",
                    (iso_year, iso_week),
                )
                this_week = cur.fetchone()

                cur.execute(
                    "SELECT * FROM weekly_summary WHERE iso_year = %s AND iso_week = %s",
                    (prev_iso_year, prev_iso_week),
                )
                prev_week = cur.fetchone()

                if not this_week:
                    logger.warning("No weekly_summary for week %s/%s", iso_year, iso_week)
                    _log_alert(
                        cur, "weekly_report", "slack", config.SLACK_REPORTS_CHANNEL,
                        False, error_message=f"No data for week {iso_week}/{iso_year}",
                    )
                    conn.commit()
                    return False

                blocks = _build_weekly_blocks(
                    this_week, prev_week, iso_year, iso_week,
                    prev_iso_week if prev_week else None,
                )

                try:
                    resp = _get_client().chat_postMessage(
                        channel=config.SLACK_REPORTS_CHANNEL,
                        blocks=blocks,
                        text=f"Weekly Summary — Week {iso_week}, {iso_year}",
                    )
                    delivered = resp["ok"]
                except SlackApiError as exc:
                    logger.error("Slack error in weekly_report: %s", exc)
                    _log_alert(
                        cur, "weekly_report", "slack", config.SLACK_REPORTS_CHANNEL,
                        False, error_message=str(exc.response.get("error", exc)),
                    )
                    conn.commit()
                    return False

                _log_alert(
                    cur, "weekly_report", "slack", config.SLACK_REPORTS_CHANNEL,
                    delivered,
                    message_preview=f"Weekly report w{iso_week}/{iso_year}",
                )
                conn.commit()

    except Exception as exc:
        logger.exception("send_weekly_report failed: %s", exc)
        _persist_failed_alert("weekly_report", config.SLACK_REPORTS_CHANNEL, str(exc))

    return delivered


# ---------------------------------------------------------------------------
# FUNCTION 3 — All Brands Summary
# ---------------------------------------------------------------------------

def send_all_brands_summary(report_date: Optional[date] = None) -> bool:
    """
    Post a cross-store summary table to SLACK_CHANNEL_ID.
    Triggered at 07:05, after daily_report completes.
    """
    if report_date is None:
        report_date = date.today() - timedelta(days=1)

    delivered = False

    try:
        with psycopg2.connect(config.POSTGRES_URL) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:

                cur.execute(
                    "SELECT * FROM daily_pl WHERE report_date = %s ORDER BY store_id",
                    (report_date,),
                )
                rows = cur.fetchall()

                if not rows:
                    logger.info("No store data for %s — skipping all_brands_summary.", report_date)
                    conn.commit()
                    return False

                blocks = _build_all_brands_blocks(report_date, rows)

                try:
                    resp = _get_client().chat_postMessage(
                        channel=config.SLACK_CHANNEL_ID,
                        blocks=blocks,
                        text=f"All Stores Summary | {report_date}",
                    )
                    delivered = resp["ok"]
                except SlackApiError as exc:
                    logger.error("Slack error in all_brands_summary: %s", exc)
                    delivered = False

                _log_alert(
                    cur, "all_brands_summary", "slack", config.SLACK_CHANNEL_ID,
                    delivered, message_preview=f"All brands {report_date} | {len(rows)} stores",
                )
                conn.commit()

    except Exception as exc:
        logger.exception("send_all_brands_summary failed: %s", exc)
        _persist_failed_alert("all_brands_summary", config.SLACK_CHANNEL_ID, str(exc))

    return delivered


# ---------------------------------------------------------------------------
# FUNCTION 4 — Anomaly Alert
# ---------------------------------------------------------------------------

_ANOMALY_META = {
    "roas": {
        "type":   "Low ROAS",
        "action": "Review ad spend targeting — check Google Ads and Pinterest campaigns.",
    },
    "refund_pct": {
        "type":   "High Refund Rate",
        "action": "Investigate product quality and order fulfilment issues.",
    },
    "profit_pct": {
        "type":   "Negative Profit",
        "action": "Review pricing, fixed costs, and margins immediately.",
    },
    "revenue": {
        "type":   "Revenue Drop",
        "action": "Check marketing campaigns, site availability, and payment processing.",
    },
}


def send_anomaly_alert(
    metric: str,
    value: float,
    threshold: float,
    message: str,
    store: str = "default",
) -> bool:
    """
    Send an instant anomaly alert to SLACK_ALERTS_CHANNEL.
    Called from main.py when pl_processor flags an anomaly.
    """
    meta        = _ANOMALY_META.get(metric, {"type": metric.upper(), "action": "Review immediately."})
    report_date = date.today() - timedelta(days=1)
    delivered   = False

    try:
        blocks = _build_anomaly_blocks(
            store, metric, value, threshold,
            meta["type"], meta["action"], report_date,
        )
        resp = _get_client().chat_postMessage(
            channel=config.SLACK_ALERTS_CHANNEL,
            blocks=blocks,
            text=f"ANOMALY: {meta['type']} — {_store_name(store)} | {metric}={value}",
        )
        delivered = resp["ok"]

        with psycopg2.connect(config.POSTGRES_URL) as conn:
            with conn.cursor() as cur:
                _log_alert(
                    cur, "anomaly", "slack", config.SLACK_ALERTS_CHANNEL,
                    delivered,
                    trigger_metric=metric,
                    trigger_value=float(value),
                    threshold_value=float(threshold),
                    message_preview=message[:500],
                )
                conn.commit()

    except SlackApiError as exc:
        err = str(exc.response.get("error", exc))
        logger.error("Slack error in send_anomaly_alert: %s", err)
        _persist_failed_alert("anomaly", config.SLACK_ALERTS_CHANNEL, err)
    except Exception as exc:
        logger.exception("send_anomaly_alert failed: %s", exc)
        _persist_failed_alert("anomaly", config.SLACK_ALERTS_CHANNEL, str(exc))

    return delivered


# ---------------------------------------------------------------------------
# FUNCTION 5 — Invoice Confirmation (thread reply)
# ---------------------------------------------------------------------------

def send_invoice_confirmation(
    channel: str,
    thread_ts: str,
    supplier: Optional[str],
    amount,
    invoice_date,
    status: str,
    error_reason: Optional[str] = None,
) -> bool:
    """
    Post a thread reply to an invoice message in SLACK_INVOICES_CHANNEL.

    status: 'success' | 'low_confidence' | 'error'
    """
    try:
        if status == "success":
            amount_str = _fmt_currency(float(amount)) if amount is not None else "N/A"
            text = (
                f"✅ *Invoice logged* — {supplier or 'Unknown supplier'} | "
                f"{amount_str} | {invoice_date or 'No date'}\n"
                f"   COG updated for store."
            )
        elif status == "low_confidence":
            text = (
                f"⚠️ *Low confidence extraction*\n"
                f"   Detected: {supplier or '?'} | "
                f"{_fmt_currency(float(amount)) if amount else '?'} | {invoice_date or '?'}\n"
                f"   Please verify and re-post with clearer format.\n"
                f"   Expected: `Supplier name | Amount | Date`"
            )
        else:
            text = (
                f"⚠️ *Could not read invoice* — please check the format.\n"
                f"   {error_reason or 'Unknown error'}\n"
                f"   Expected: `Supplier name | Amount | Date`"
            )

        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": text}}
        ]

        resp = _get_client().chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            blocks=blocks,
            text=text,
        )

        with psycopg2.connect(config.POSTGRES_URL) as conn:
            with conn.cursor() as cur:
                _log_alert(
                    cur, "invoice_confirmation", "slack", channel,
                    resp["ok"],
                    trigger_metric="invoice",
                    message_preview=text[:300],
                )
                conn.commit()

        return resp["ok"]

    except SlackApiError as exc:
        logger.error("Slack error in send_invoice_confirmation: %s", exc)
        return False
    except Exception as exc:
        logger.exception("send_invoice_confirmation failed: %s", exc)
        return False
