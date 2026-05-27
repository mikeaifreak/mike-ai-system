"""
slack_invoice_reader.py — Poll #supplier-invoices Slack channel for invoice messages.

Runs every 30 minutes (triggered by scheduler.py → main.py --mode read_invoices).

Flow:
  1. Fetch conversation history from SLACK_INVOICES_CHANNEL since last processed ts.
  2. For each new message that looks like an invoice:
       a. Send message text to GPT-4o for structured field extraction.
       b. confidence >= 0.8 → insert to reconciliation_log, reply with success confirmation.
       c. confidence < 0.8  → reply with low_confidence confirmation, log warning.
       d. any exception     → reply with error confirmation, log warning to agent_runs.
  3. Update slack_sync_state.last_ts to most recent message ts.

All credentials come from environment variables via config.py — zero hardcoded values.
"""

import json
import logging
from datetime import date
from typing import Optional

import psycopg2
from openai import OpenAI
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

import config
from slack_reporter import send_invoice_confirmation

logger = logging.getLogger("finance_ai.slack_invoice_reader")

# ---------------------------------------------------------------------------
# GPT extraction prompt
# ---------------------------------------------------------------------------

_EXTRACTION_SYSTEM = """\
You are a finance data extraction assistant.
Extract invoice details from Slack messages posted by suppliers.

Return ONLY a valid JSON object with exactly these fields:
{
  "supplier":     string or null,
  "amount":       number or null,
  "currency":     string (e.g. "EUR", "USD", "GBP") or null,
  "invoice_date": string "YYYY-MM-DD" or null,
  "confidence":   float 0.0 to 1.0
}

Confidence rubric:
  0.9 – 1.0 : clear invoice with supplier, amount, and date
  0.7 – 0.9 : likely invoice, one or two fields missing or inferred
  0.5 – 0.7 : ambiguous — could be invoice but key data missing
  0.0 – 0.5 : not an invoice or not enough information

Return ONLY valid JSON, no markdown fences, no explanation.\
"""

_EXTRACTION_USER_TMPL = "Extract invoice details from this message:\n\n{text}"

CONFIDENCE_THRESHOLD: float = 0.8

# Minimum message length worth sending to GPT (short messages are almost never invoices)
_MIN_TEXT_LEN = 20


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _get_last_ts(conn, channel_id: str) -> Optional[str]:
    """Return the last processed Slack message ts for channel, or None."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT last_ts FROM slack_sync_state WHERE channel_id = %s",
            (channel_id,),
        )
        row = cur.fetchone()
        return row[0] if row else None


def _set_last_ts(conn, channel_id: str, last_ts: str) -> None:
    """Upsert last processed Slack message ts for channel."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO slack_sync_state (channel_id, last_ts, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (channel_id) DO UPDATE
            SET last_ts = EXCLUDED.last_ts, updated_at = NOW()
            """,
            (channel_id, last_ts),
        )
    conn.commit()


def _insert_reconciliation(conn, supplier: str, amount, currency: str,
                           invoice_date: str) -> None:
    """Log a successfully extracted invoice to reconciliation_log."""
    notes = (
        f"Invoice extracted from Slack: supplier={supplier}, "
        f"amount={amount} {currency}, invoice_date={invoice_date}"
    )
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO reconciliation_log
                (run_date, status, notes, agent_name, model_used)
            VALUES (%s, 'ok', %s, 'slack_invoice_reader', %s)
            """,
            (date.today(), notes, config.GPT_MODEL),
        )
    conn.commit()


def _log_agent_run(conn, status: str, notes: Optional[str] = None) -> None:
    """Append a row to agent_runs for this invoice reader execution."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_runs
                (agent_name, workflow_name, trigger_type, status,
                 finished_at, error_message, model)
            VALUES ('slack_invoice_reader', 'read_invoices', 'cron',
                    %s, NOW(), %s, %s)
            """,
            (status, notes, config.GPT_MODEL),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# GPT-4o extraction
# ---------------------------------------------------------------------------

def _extract_invoice(text: str) -> dict:
    """Send message text to GPT-4o; return parsed extraction dict."""
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    response = client.chat.completions.create(
        model=config.GPT_MODEL,
        messages=[
            {"role": "system", "content": _EXTRACTION_SYSTEM},
            {"role": "user",   "content": _EXTRACTION_USER_TMPL.format(text=text)},
        ],
        temperature=0.0,
        max_tokens=256,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content or "{}"
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Message filter
# ---------------------------------------------------------------------------

def _is_invoice_candidate(msg: dict) -> bool:
    """Return True only for human messages long enough to be an invoice."""
    # Skip bot/app messages (our own confirmation replies live here too)
    if msg.get("subtype") in ("bot_message", "slackbot_response"):
        return False
    # Skip thread replies — only process top-level messages (thread_ts == ts)
    if msg.get("thread_ts") and msg.get("thread_ts") != msg.get("ts"):
        return False
    text = msg.get("text", "").strip()
    if len(text) < _MIN_TEXT_LEN:
        return False
    if not msg.get("ts"):
        return False
    return True


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run() -> None:
    """
    Poll SLACK_INVOICES_CHANNEL for new messages and process each as a
    potential invoice using GPT-4o extraction.

    Called by main.py (mode=read_invoices) every 30 minutes.
    """
    channel_id = config.SLACK_INVOICES_CHANNEL
    logger.info("=== slack_invoice_reader.run() | channel=%s ===", channel_id)

    slack = WebClient(token=config.SLACK_BOT_TOKEN)

    try:
        conn = psycopg2.connect(config.POSTGRES_URL)
    except Exception as exc:
        logger.error("DB connection failed — aborting invoice reader: %s", exc)
        return

    try:
        last_ts = _get_last_ts(conn, channel_id)
        logger.info("Last processed ts: %s", last_ts or "(none — first run)")

        # ------------------------------------------------------------------
        # Fetch channel history
        # ------------------------------------------------------------------
        fetch_kwargs: dict = {"channel": channel_id, "limit": 100}
        if last_ts:
            fetch_kwargs["oldest"] = last_ts   # exclusive: returns only newer msgs

        try:
            resp = slack.conversations_history(**fetch_kwargs)
        except SlackApiError as exc:
            logger.error("Slack conversations.history error: %s", exc)
            _log_agent_run(conn, "error", str(exc))
            return

        messages = resp.get("messages", [])
        logger.info("Fetched %d message(s) since last run", len(messages))

        if not messages:
            _log_agent_run(conn, "success")
            return

        # Slack returns newest-first — process oldest-first so last_ts advances correctly
        messages = list(reversed(messages))
        newest_ts: str = messages[-1].get("ts", last_ts or "")

        candidates = [m for m in messages if _is_invoice_candidate(m)]
        logger.info(
            "%d message(s) are invoice candidates (of %d total)",
            len(candidates), len(messages),
        )

        processed = 0
        warnings  = 0

        for msg in candidates:
            text     = msg.get("text", "")
            msg_ts   = msg.get("ts", "")
            # Reply in the thread of the original message
            thread_ts = msg_ts

            logger.info("Processing ts=%s (len=%d chars)", msg_ts, len(text))

            # ------------------------------------------------------------------
            # GPT extraction
            # ------------------------------------------------------------------
            extracted: dict = {}
            try:
                extracted = _extract_invoice(text)
                logger.info("Extraction result: %s", extracted)
            except Exception as exc:
                logger.warning("GPT extraction failed for ts=%s: %s", msg_ts, exc)
                send_invoice_confirmation(
                    channel      = channel_id,
                    thread_ts    = thread_ts,
                    supplier     = None,
                    amount       = None,
                    invoice_date = None,
                    status       = "error",
                    error_reason = f"GPT extraction failed: {exc}",
                )
                warnings += 1
                continue

            supplier     = extracted.get("supplier") or "Unknown Supplier"
            amount       = extracted.get("amount")
            currency     = extracted.get("currency") or "EUR"
            invoice_date = extracted.get("invoice_date") or str(date.today())
            confidence   = float(extracted.get("confidence", 0.0))

            # ------------------------------------------------------------------
            # Route by confidence
            # ------------------------------------------------------------------
            if confidence >= CONFIDENCE_THRESHOLD:
                # High confidence — store and confirm
                try:
                    _insert_reconciliation(conn, supplier, amount, currency, invoice_date)
                    logger.info(
                        "Reconciliation inserted: supplier=%s amount=%s %s date=%s",
                        supplier, amount, currency, invoice_date,
                    )
                except Exception as exc:
                    logger.warning("reconciliation_log insert failed: %s", exc)

                send_invoice_confirmation(
                    channel      = channel_id,
                    thread_ts    = thread_ts,
                    supplier     = supplier,
                    amount       = amount,
                    invoice_date = invoice_date,
                    status       = "success",
                )
                processed += 1

            else:
                # Low confidence — flag for review
                logger.info(
                    "Low confidence (%.0f%%) for ts=%s — not inserting",
                    confidence * 100, msg_ts,
                )
                send_invoice_confirmation(
                    channel      = channel_id,
                    thread_ts    = thread_ts,
                    supplier     = supplier,
                    amount       = amount,
                    invoice_date = invoice_date,
                    status       = "low_confidence",
                    error_reason = (
                        f"Confidence {confidence:.0%} is below the "
                        f"{CONFIDENCE_THRESHOLD:.0%} threshold — please verify manually."
                    ),
                )
                warnings += 1

        # ------------------------------------------------------------------
        # Advance last_ts so we don't reprocess these messages next run
        # ------------------------------------------------------------------
        if newest_ts and newest_ts != last_ts:
            _set_last_ts(conn, channel_id, newest_ts)
            logger.info("Updated last_ts → %s", newest_ts)

        final_status = "warning" if warnings > 0 and processed == 0 else "success"
        run_notes = f"processed={processed} warnings={warnings}"
        _log_agent_run(conn, final_status, run_notes if warnings > 0 else None)
        logger.info("Invoice reader complete: %s", run_notes)

    except Exception as exc:
        logger.exception("Unhandled error in slack_invoice_reader.run(): %s", exc)
        try:
            _log_agent_run(conn, "error", str(exc))
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
