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
SLACK_BOT_TOKEN: str  = _require("SLACK_BOT_TOKEN")
SLACK_CHANNEL_ID: str = _require("SLACK_CHANNEL_ID")

# Channel-specific overrides — fall back to SLACK_CHANNEL_ID if not set
SLACK_REPORTS_CHANNEL:  str = os.getenv("SLACK_REPORTS_CHANNEL")  or SLACK_CHANNEL_ID
SLACK_ALERTS_CHANNEL:   str = os.getenv("SLACK_ALERTS_CHANNEL")   or SLACK_CHANNEL_ID
SLACK_INVOICES_CHANNEL: str = os.getenv("SLACK_INVOICES_CHANNEL") or SLACK_CHANNEL_ID

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
# Shopify Admin REST API (optional — required for pull_shopify mode)
# ---------------------------------------------------------------------------
SHOPIFY_STORE_URL:  str = os.getenv("SHOPIFY_STORE_URL", "")
SHOPIFY_API_TOKEN:  str = os.getenv("SHOPIFY_API_TOKEN", "")
SHOPIFY_CLIENT_ID:  str = os.getenv("SHOPIFY_CLIENT_ID", "")
SHOPIFY_CLIENT_SECRET: str = os.getenv("SHOPIFY_CLIENT_SECRET", "")

# ---------------------------------------------------------------------------
# Google Ads spend sheets (optional — required for pull_google_ads mode)
#
# Mike installs scripts/google-ads-script.js in each Google Ads account.
# The script writes daily campaign rows to a Google Sheet.
# Each sheet is exposed via a Google Apps Script web app URL.
# No Google Ads API credentials are needed here — auth is handled inside
# the Google Ads Script running in Mike's account.
#
# GOOGLE_ADS_SHEET_URLS formats (same pattern as GOOGLE_SCRIPT_URL):
#   Single store:  "https://script.google.com/macros/s/.../exec"
#                  → {"default": url}
#   Multi-store:   "store_nl:https://...,store_de:https://..."
#                  → {"store_nl": url, "store_de": url}
#   JSON map:      '{"store_nl":"https://...","store_de":"https://..."}'
# ---------------------------------------------------------------------------
def _parse_ads_sheet_urls(raw: str) -> dict:
    """Parse GOOGLE_ADS_SHEET_URLS into a dict[store_id → apps_script_url]."""
    stripped = raw.strip()
    if not stripped:
        return {}

    # JSON map format
    if stripped.startswith("{"):
        try:
            mapping = json.loads(stripped)
            return {str(k): str(v) for k, v in mapping.items()}
        except json.JSONDecodeError as exc:
            raise EnvironmentError(
                f"GOOGLE_ADS_SHEET_URLS looks like JSON but failed to parse: {exc}"
            ) from exc

    # Check for store:url,store:url format — URLs contain "://" so we split
    # on the first comma only if it appears AFTER a complete URL segment.
    # Strategy: split on comma, then check if each part has a non-URL colon.
    parts = []
    current = ""
    for char in stripped:
        if char == "," and "://" in current:
            parts.append(current.strip())
            current = ""
        else:
            current += char
    if current.strip():
        parts.append(current.strip())

    if len(parts) == 1:
        part = parts[0]
        # store_name:https://... format?
        if "://" in part and part.index(":") < part.index("://"):
            store, url = part.split(":", 1)
            return {store.strip(): url.strip()}
        return {"default": part}

    # Multiple parts — must be store:url format
    result = {}
    for part in parts:
        if "://" not in part:
            raise EnvironmentError(
                f"GOOGLE_ADS_SHEET_URLS part does not look like a URL: {part!r}"
            )
        colon_before_scheme = part.index(":") < part.index("://")
        if colon_before_scheme:
            store, url = part.split(":", 1)
            result[store.strip()] = url.strip()
        else:
            raise EnvironmentError(
                f"Multiple URLs in GOOGLE_ADS_SHEET_URLS require store names. "
                f"Use 'store_nl:https://...,store_de:https://...' format."
            )
    return result


GOOGLE_ADS_STORE_SHEET_URLS: dict = _parse_ads_sheet_urls(
    os.getenv("GOOGLE_ADS_SHEET_URLS", "")
)

# ---------------------------------------------------------------------------
# Pinterest Ads spend sheets (optional — required for pull_pinterest_ads mode)
#
# Same URL format as GOOGLE_ADS_SHEET_URLS.
# ---------------------------------------------------------------------------
PINTEREST_ADS_STORE_SHEET_URLS: dict = _parse_ads_sheet_urls(
    os.getenv("PINTEREST_ADS_SHEET_URLS", "")
)

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
