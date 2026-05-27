"""
routes/chat.py — NOVA streaming chat + per-agent chat endpoints.

Endpoints:
  POST /chat/         → NOVA general-purpose finance assistant
  POST /chat/agent    → Agent-specific chat (reconcile, sync, slack, whatsapp, trend, keyword)
"""

import asyncio
import os
import sys
from typing import AsyncIterator

import anthropic
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator

from auth import get_current_user
from db import get_conn
from nova import stream_nova_response

router = APIRouter(prefix="/chat", tags=["chat"])


# ---------------------------------------------------------------------------
# NOVA — existing general chat endpoint (unchanged)
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str

    @field_validator("message")
    @classmethod
    def message_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("message must not be empty")
        if len(v) > 500:
            raise ValueError("message must be 500 characters or fewer")
        return v


@router.post("/")
async def chat(
    body: ChatRequest,
    current_user: str = Depends(get_current_user),
):
    async def event_stream():
        try:
            with get_conn() as conn:
                async for chunk in stream_nova_response(body.message, conn):
                    yield f"data: {chunk}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: [ERROR] {str(e)}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Agent Chat — per-agent personas, DB context, optional command execution
# ---------------------------------------------------------------------------

AGENT_PERSONAS: dict[str, str] = {
    "Finance Reconciliation Agent": (
        "You are the Finance Reconciliation Agent for Mike's e-commerce business (Frugaze, Netherlands). "
        "You monitor P&L data accuracy, catch mismatches between Shopify and the Google Sheet, and flag "
        "late invoices. Answer questions about reconciliation runs, mismatches, and data integrity. "
        "Be precise and direct. Use bullet points and exact numbers where available. "
        "Keep responses under 200 words."
    ),
    "Google Sheets Sync Agent": (
        "You are the Google Sheets Sync Agent for Mike's e-commerce business (Frugaze). "
        "You pull P&L data from Mike's Google Sheets and store it in PostgreSQL. "
        "Answer questions about sync status, row counts, last sync timestamps, and any parsing errors. "
        "Be technical and precise. Keep responses under 150 words."
    ),
    "Slack Reporter Agent": (
        "You are the Slack Reporter Agent for Mike's e-commerce business (Frugaze). "
        "You send daily P&L reports and anomaly alerts to the Slack channel. "
        "Answer questions about report delivery, last report content, and Slack alert history. "
        "State times in Europe/Amsterdam timezone. Keep responses under 150 words."
    ),
    "WhatsApp Alerts Agent": (
        "You are the WhatsApp Alerts Agent for Mike's e-commerce business (Frugaze). "
        "You send end-of-day finance summaries to Mike via WhatsApp Business API (Meta Cloud). "
        "Answer questions about last message delivery, alert history, and connection status. "
        "Be concise. Keep responses under 150 words."
    ),
    "Trend Watcher Agent": (
        "You are the Trend Watcher Agent for Mike's e-commerce business (Frugaze). "
        "You monitor product and market trends relevant to the business. "
        "Answer questions about current trends, anomalies, and performance patterns. "
        "Be insightful and data-driven. Keep responses under 200 words."
    ),
    "Keyword Intelligence Agent": (
        "You are the Keyword Intelligence Agent for Mike's e-commerce business (Frugaze). "
        "You analyze keyword competition scores and search trends for the business. "
        "Answer questions about top keywords, competition levels, and export options. "
        "Be analytical and specific. Keep responses under 200 words."
    ),
}

# Pipeline mode each agent can trigger directly
AGENT_MODES: dict[str, str | None] = {
    "Finance Reconciliation Agent": "reconcile",
    "Google Sheets Sync Agent":     "sync_only",
    "Slack Reporter Agent":         "morning_report",
    "WhatsApp Alerts Agent":        "eod_report",
    "Trend Watcher Agent":          None,
    "Keyword Intelligence Agent":   None,
}

COMMAND_KEYWORDS = frozenset({"run", "sync", "send", "execute", "trigger"})


def _is_command(message: str) -> bool:
    words = message.strip().lower().split()
    return bool(words) and words[0] in COMMAND_KEYWORDS


def _get_agent_context(agent_name: str, conn) -> str:
    """Query the relevant DB table(s) to build context for the agent's Claude response."""
    try:
        with conn.cursor() as cur:

            if "Reconciliation" in agent_name:
                cur.execute(
                    "SELECT run_date, sheet_row_count, db_row_count, mismatches, status, notes "
                    "FROM reconciliation_log ORDER BY run_date DESC LIMIT 10"
                )
                rows = cur.fetchall()
                if not rows:
                    return "No reconciliation runs recorded yet."
                lines = ["Last 10 reconciliation runs:"]
                for r in rows:
                    lines.append(
                        f"  {r[0]}: sheet={r[1]} rows, db={r[2]} rows, "
                        f"mismatches={r[3]}, status={r[4]}"
                        + (f", notes: {r[5]}" if r[5] else "")
                    )
                return "\n".join(lines)

            elif "Sheets Sync" in agent_name:
                cur.execute(
                    "SELECT agent_name, workflow_name, status, started_at, duration_ms, error_message "
                    "FROM agent_runs ORDER BY started_at DESC LIMIT 10"
                )
                rows = cur.fetchall()
                if not rows:
                    return "No sync run history found."
                lines = ["Last 10 agent runs:"]
                for r in rows:
                    err = f" | ERROR: {r[5]}" if r[5] else ""
                    lines.append(f"  [{r[3]}] {r[0]} / {r[1]} — {r[2]} ({r[4]}ms){err}")
                return "\n".join(lines)

            elif agent_name in ("Slack Reporter Agent", "WhatsApp Alerts Agent"):
                channel = "slack" if "Slack" in agent_name else "whatsapp"
                try:
                    cur.execute(
                        "SELECT sent_at, channel, status, error_message "
                        "FROM alerts_log WHERE channel = %s ORDER BY sent_at DESC LIMIT 10",
                        (channel,),
                    )
                    rows = cur.fetchall()
                    if not rows:
                        return f"No {channel} alerts recorded yet."
                    lines = [f"Last {channel} alerts:"]
                    for r in rows:
                        err = f" | error: {r[3]}" if r[3] else ""
                        lines.append(f"  {r[0]}: status={r[2]}{err}")
                    return "\n".join(lines)
                except Exception:
                    # alerts_log may not exist yet — fall back to agent_runs
                    cur.execute(
                        "SELECT agent_name, workflow_name, status, started_at "
                        "FROM agent_runs ORDER BY started_at DESC LIMIT 5"
                    )
                    rows = cur.fetchall()
                    if not rows:
                        return "No run history found."
                    return "Recent agent runs:\n" + "\n".join(
                        f"  {r[0]} — {r[2]} at {r[3]}" for r in rows
                    )

            else:
                # Trend Watcher / Keyword Intelligence — recent general activity
                cur.execute(
                    "SELECT agent_name, workflow_name, status, started_at, duration_ms "
                    "FROM agent_runs ORDER BY started_at DESC LIMIT 10"
                )
                rows = cur.fetchall()
                if not rows:
                    return "No agent run history found."
                lines = ["Recent agent activity:"]
                for r in rows:
                    lines.append(
                        f"  [{r[3]}] {r[0]} / {r[1]} — {r[2]} ({r[4]}ms)"
                    )
                return "\n".join(lines)

    except Exception as exc:
        return f"Context unavailable: {exc}"


async def _stream_agent_response(
    agent_name: str,
    message: str,
    context: str,
) -> AsyncIterator[str]:
    """Yield Claude response chunks using the agent's persona and DB context."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        yield "ANTHROPIC_API_KEY is not configured."
        return

    model = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
    system_prompt = AGENT_PERSONAS.get(
        agent_name, "You are a helpful AI agent for an e-commerce business."
    )
    client = anthropic.AsyncAnthropic(api_key=api_key)

    full_message = (
        f"Current database context:\n{context}\n\nUser question: {message}"
    )

    async with client.messages.stream(
        model=model,
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": full_message}],
    ) as stream:
        async for text in stream.text_stream:
            yield text


async def _stream_command_output(mode: str) -> AsyncIterator[str]:
    """
    Execute a pipeline mode and stream its stdout/stderr line-by-line.

    Requires PIPELINE_MAIN_PATH env var = absolute path to scripts/python/main.py
    (must be accessible from the backend container).
    When not set, returns a confirmation message instead of running anything.
    """
    pipeline_path = os.getenv("PIPELINE_MAIN_PATH", "")
    if not pipeline_path or not os.path.isfile(pipeline_path):
        yield f"> mode: {mode}"
        yield "\n> Pipeline executor is not directly reachable from this container."
        yield "\n> The job will fire at its next scheduled time via the scheduler."
        yield "\n> To enable direct execution: set PIPELINE_MAIN_PATH=/path/to/scripts/python/main.py"
        yield "\n>   and mount that path into the backend container."
        return

    yield f"> python main.py --mode {mode}\n"
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            pipeline_path,
            "--mode",
            mode,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=os.path.dirname(pipeline_path),
        )
        async for raw_line in proc.stdout:  # type: ignore[union-attr]
            yield raw_line.decode("utf-8", errors="replace").rstrip("\n") + "\n"
        await proc.wait()
        yield f"\n> Done — exit code {proc.returncode}"
    except Exception as exc:
        yield f"\n> [ERROR] {exc}"


# ---------------------------------------------------------------------------
# Request model + endpoint
# ---------------------------------------------------------------------------

class AgentChatRequest(BaseModel):
    agent_name: str
    message: str

    @field_validator("agent_name")
    @classmethod
    def validate_agent(cls, v: str) -> str:
        if v not in AGENT_PERSONAS:
            raise ValueError(f"Unknown agent: {v!r}")
        return v

    @field_validator("message")
    @classmethod
    def message_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("message must not be empty")
        if len(v) > 1000:
            raise ValueError("message must be 1000 characters or fewer")
        return v


@router.post("/agent")
async def agent_chat(
    body: AgentChatRequest,
    current_user: str = Depends(get_current_user),
):
    async def event_stream():
        try:
            if _is_command(body.message):
                mode = AGENT_MODES.get(body.agent_name)
                if mode:
                    async for line in _stream_command_output(mode):
                        yield f"data: {line}\n\n"
                else:
                    yield (
                        f"data: {body.agent_name} does not have a direct execution "
                        f"mode yet — this agent is currently under development.\n\n"
                    )
            else:
                with get_conn() as conn:
                    context = _get_agent_context(body.agent_name, conn)
                async for chunk in _stream_agent_response(
                    body.agent_name, body.message, context
                ):
                    yield f"data: {chunk}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: [ERROR] {str(e)}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
