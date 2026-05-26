"""
config.py — Centralised credential + settings loader.
All values come from environment variables (loaded from .env by python-dotenv).
"""

import os
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise EnvironmentError(f"Required environment variable '{key}' is not set.")
    return val


# ---------------------------------------------------------------------------
# Google Sheets (via Apps Script web app)
# ---------------------------------------------------------------------------
GOOGLE_SCRIPT_URL: str = _require("GOOGLE_SCRIPT_URL")

# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------
POSTGRES_URL: str = _require("POSTGRES_URL")

# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------
SLACK_BOT_TOKEN: str = _require("SLACK_BOT_TOKEN")
SLACK_CHANNEL_ID: str = _require("SLACK_CHANNEL_ID")

# ---------------------------------------------------------------------------
# AI models
# ---------------------------------------------------------------------------
ANTHROPIC_API_KEY: str = _require("ANTHROPIC_API_KEY")
OPENAI_API_KEY: str = _require("OPENAI_API_KEY")

CLAUDE_MODEL: str = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
GPT_MODEL: str    = os.getenv("GPT_MODEL",    "gpt-4o")

# ---------------------------------------------------------------------------
# WhatsApp Business Cloud API (Meta)
# ---------------------------------------------------------------------------
WHATSAPP_ACCESS_TOKEN:       str = _require("WHATSAPP_ACCESS_TOKEN")
WHATSAPP_PHONE_NUMBER_ID:    str = _require("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_RECIPIENT_NUMBER:   str = _require("WHATSAPP_RECIPIENT_NUMBER")
WHATSAPP_API_VERSION:        str = os.getenv("WHATSAPP_API_VERSION", "v18.0")

# ---------------------------------------------------------------------------
# Anomaly thresholds (override via env if needed)
# ---------------------------------------------------------------------------
THRESHOLD_ROAS_LOW:        float = float(os.getenv("THRESHOLD_ROAS_LOW",     "1.5"))
THRESHOLD_REFUND_PCT_HIGH: float = float(os.getenv("THRESHOLD_REFUND_PCT_HIGH", "10.0"))

# ---------------------------------------------------------------------------
# Pipeline settings
# ---------------------------------------------------------------------------
# How many trailing days to always re-sync (catches late supplier invoices)
REPROCESS_WINDOW_DAYS: int = int(os.getenv("REPROCESS_WINDOW_DAYS", "7"))

# Sheet tab name
SHEET_TAB_NAME: str = os.getenv("SHEET_TAB_NAME", "Sheet1")
