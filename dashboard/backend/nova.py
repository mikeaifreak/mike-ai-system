import os
from typing import AsyncGenerator

import anthropic
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

SYSTEM_PROMPT = (
    "You are NOVA, Mike's AI Finance Assistant for his e-commerce business. "
    "You have access to his live P&L database. "
    "Answer in 2-3 sentences max. Always lead with the specific number. "
    "Be direct. No fluff. Format currency as $X,XXX. Format ROAS as X.XX."
)

_INTENT_KEYWORDS = {
    "profit": ["profit", "margin"],
    "revenue": ["revenue", "sales"],
    "roas": ["roas", "adspend", "spend"],
    "agent_status": ["agent", "system", "sync"],
    "anomaly": ["anomaly", "alert", "flag"],
}


def classify_intent(message: str) -> str:
    lower = message.lower()
    for intent, keywords in _INTENT_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            return intent
    return "general"


def fetch_context(intent: str, conn) -> str:
    queries = {
        "profit": (
            "SELECT report_date, profit, profit_pct "
            "FROM daily_pl ORDER BY report_date DESC LIMIT 7"
        ),
        "revenue": (
            "SELECT report_date, revenue "
            "FROM daily_pl ORDER BY report_date DESC LIMIT 7"
        ),
        "roas": (
            "SELECT report_date, roas, adspend_google "
            "FROM daily_pl ORDER BY report_date DESC LIMIT 14"
        ),
        "agent_status": (
            "SELECT agent_name, status, started_at, duration_ms "
            "FROM agent_runs "
            "WHERE started_at > NOW() - INTERVAL '24 hours' "
            "ORDER BY started_at DESC LIMIT 10"
        ),
        "anomaly": (
            "SELECT alert_type, message_preview, sent_at "
            "FROM alerts_log "
            "WHERE alert_type = 'anomaly' "
            "ORDER BY sent_at DESC LIMIT 5"
        ),
        "general": "SELECT * FROM mtd_summary LIMIT 1",
    }

    sql = queries.get(intent, queries["general"])
    conn.execute(sql)
    rows = conn.fetchall()

    if not rows:
        return "No data available."

    lines = []
    for row in rows:
        lines.append(", ".join(f"{k}: {v}" for k, v in dict(row).items()))
    return "\n".join(lines)


async def stream_nova_response(message: str, conn) -> AsyncGenerator[str, None]:
    intent = classify_intent(message)
    context = fetch_context(intent, conn)

    user_content = (
        f"Live database context ({intent}):\n{context}\n\nUser question: {message}"
    )

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    with client.messages.stream(
        model=CLAUDE_MODEL,
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    ) as stream:
        for text in stream.text_stream:
            yield text

    # Log the chat interaction
    conn.execute(
        """
        INSERT INTO alerts_log
            (alert_type, channel, message_preview, delivered)
        VALUES
            (%s, %s, %s, %s)
        """,
        ("nova_chat", "nova", message[:500], True),
    )
