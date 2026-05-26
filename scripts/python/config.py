"""
config.py — Centralised credential + settings loader.
All values come from environment variables (loaded from .env by python-dotenv).
"""

import json
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
#
# GOOGLE_SCRIPT_URL supports two formats:
#
#   Single store (current):
#     GOOGLE_SCRIPT_URL=https://script.google.com/macros/s/.../exec
#     → parsed as {"default": "<url>"}
#
#   Multi-store (future — when Mike has multiple Shopify stores):
#     GOOGLE_SCRIPT_URL={"store_nl":"https://...","store_de":"https://..."}
#     → each store_id maps to its own Apps Script URL
#
# To activate multi-store: iterate config.GOOGLE_STORE_URLS.items() in main.py
# and call _sync_sheets_to_db(store_id=sid, url=url) for each.
# ---------------------------------------------------------------------------
def _parse_store_urls(raw: str) -> dict:
    stripped = raw.strip()
    if stripped.startswith("{"):
        try:
            mapping = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise EnvironmentError(
                f"GOOGLE_SCRIPT_URL looks like JSON but failed to parse: {exc}"
            ) from exc
        if not mapping:
            raise EnvironmentError("GOOGLE_SCRIPT_URL JSON map is empty.")
        return {str(k): str(v) for k, v in mapping.items()}
    return {"default": stripped}


_raw_script_url: str = _require("GOOGLE_SCRIPT_URL")

# dict[store_id → url] — single entry now, multi-store ready
GOOGLE_STORE_URLS: dict = _parse_store_urls(_raw_script_url)

# Convenience: URL for the first (currently only) store
GOOGLE_SCRIPT_URL: str = next(iter(GOOGLE_STORE_URLS.values()))

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
