"""
whatsapp_alerts.py — Sends WhatsApp messages via Meta Business Cloud API v18.0.
"""

import logging
from datetime import date
from typing import Optional

import requests
import psycopg2
import psycopg2.extras

import config

logger = logging.getLogger(__name__)

WA_API_URL = (
    "https://graph.facebook.com/{version}//{phone_id}/messages"
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_api_url() -> str:
    return (
        f"https://graph.facebook.com/{config.WHATSAPP_API_VERSION}"
        f"/{config.WHATSAPP_PHONE_NUMBER_ID}/messages"
    )


def _build_headers() -> dict:
    return {
        "Authorization": f"Bearer {config.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def _log_alert(
    cursor,
    alert_type: str,
    recipient: str,
    delivered: bool,
    message_preview: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    cursor.execute("""
        INSERT INTO alerts_log (
            alert_type, channel, recipient,
            message_preview, delivered, error_message
        ) VALUES (%s, 'whatsapp', %s, %s, %s, %s)
    """, (alert_type, recipient, message_preview, delivered, error_message))


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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def send_whatsapp_message(message: str) -> bool:
    """
    Send a plain-text WhatsApp message to WHATSAPP_RECIPIENT_NUMBER via
    Meta Cloud API v18.0.

    Returns True if the API accepted the message (HTTP 200).
    """
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type":    "individual",
        "to":                config.WHATSAPP_RECIPIENT_NUMBER,
        "type":              "text",
        "text": {
            "preview_url": False,
            "body":        message,
        },
    }

    delivered  = False
    error_msg  = None

    try:
        response = requests.post(
            _build_api_url(),
            headers=_build_headers(),
            json=payload,
            timeout=15,
        )
        response.raise_for_status()
        delivered = True
        logger.info(
            "WhatsApp message delivered to %s | msg_id=%s",
            config.WHATSAPP_RECIPIENT_NUMBER,
            response.json().get("messages", [{}])[0].get("id", "unknown"),
        )
    except requests.HTTPError as exc:
        error_msg = f"HTTP {exc.response.status_code}: {exc.response.text[:300]}"
        logger.error("WhatsApp API HTTP error: %s", error_msg)
    except requests.RequestException as exc:
        error_msg = str(exc)
        logger.error("WhatsApp API request error: %s", error_msg)

    # Persist result to alerts_log
    try:
        with psycopg2.connect(config.POSTGRES_URL) as conn:
            with conn.cursor() as cur:
                _log_alert(
                    cur,
                    alert_type      = "whatsapp_message",
                    recipient       = config.WHATSAPP_RECIPIENT_NUMBER,
                    delivered       = delivered,
                    message_preview = message[:500],
                    error_message   = error_msg,
                )
                conn.commit()
    except Exception as log_exc:
        logger.warning("Could not persist WhatsApp alert to DB: %s", log_exc)

    return delivered


def send_eod_summary() -> bool:
    """
    Query today's daily_pl row, format a short EOD summary, and send it
    via WhatsApp to Mike.

    Intended to be called at 21:00 by the scheduler / n8n cron.
    """
    today = date.today()

    try:
        with psycopg2.connect(config.POSTGRES_URL) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM daily_pl WHERE report_date = %s",
                    (today,),
                )
                row = cur.fetchone()
    except Exception as exc:
        logger.exception("Could not fetch daily_pl for EOD summary: %s", exc)
        return False

    if row is None:
        logger.warning("No daily_pl row found for today (%s) — skipping EOD WhatsApp.", today)
        return False

    # Build anomaly lines
    alerts: list[str] = []
    roas = row.get("roas")
    if roas is not None and roas < config.THRESHOLD_ROAS_LOW:
        alerts.append(f"⚠️ Low ROAS: {_fmt_roas(roas)}")
    ref_pct = row.get("refund_pct")
    if ref_pct is not None and ref_pct > config.THRESHOLD_REFUND_PCT_HIGH:
        alerts.append(f"⚠️ High Refunds: {_fmt_pct(ref_pct)}")
    p_pct = row.get("profit_pct")
    if p_pct is not None and p_pct < 0:
        alerts.append(f"🔴 Negative Margin: {_fmt_pct(p_pct)}")

    alert_section = ("\n" + "\n".join(alerts)) if alerts else "\n✅ All metrics normal"

    message = (
        f"📊 EOD Finance Summary — {today.strftime('%d %b %Y')}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Revenue:  {_fmt_currency(row.get('revenue'))}\n"
        f"💵 Profit:   {_fmt_currency(row.get('profit'))} ({_fmt_pct(row.get('profit_pct'))})\n"
        f"📈 ROAS:     {_fmt_roas(row.get('roas'))}\n"
        f"📣 Ad Spend: {_fmt_currency(row.get('adspend_google'))}\n"
        f"↩️  Refunds:  {_fmt_currency(row.get('refunds'))} ({_fmt_pct(row.get('refund_pct'))})\n"
        f"━━━━━━━━━━━━━━━━━━━━"
        f"{alert_section}"
    )

    logger.info("Sending EOD WhatsApp summary for %s", today)
    return send_whatsapp_message(message)
