"""
currency_converter.py — Daily FX rate fetching and caching.

Uses the free tier of exchangerate-api.com (1,500 requests/month — well within
the project's needs of ~60 rate fetches/month).

API endpoint:
    GET https://v6.exchangerate-api.com/v6/{key}/pair/{FROM}/{TO}
    → { "result": "success", "conversion_rate": 0.921500 }

Cache table:
    exchange_rates (rate_date, from_currency, to_currency, rate)
    — one row per currency pair per day, UNIQUE constraint prevents duplicates.

Fallback chain (get_daily_rate):
    1. Check exchange_rates cache for the requested date
    2. Fetch from API if not cached, then cache
    3. Fall back to most-recent cached rate if API is unavailable (log warning)
    4. Return 1.0 if absolutely nothing is available (log error)

Scheduler job: 06:35 daily → MODE=fetch_exchange_rates in main.py
  This runs before pull_shopify (06:40) so rates are always in the cache
  when pl_processor.py needs them.

All credentials come from environment variables via config.py.
"""

import logging
from datetime import date
from typing import Optional

import psycopg2
import requests

import config

logger = logging.getLogger("finance_ai.currency_converter")

# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

_API_URL = "https://v6.exchangerate-api.com/v6/{key}/pair/{from_c}/{to_c}"
_REQUEST_TIMEOUT = 10  # seconds

# Currency pairs to fetch every day.
# Extend this list when Mike adds stores with new currencies.
_DAILY_PAIRS: list[tuple[str, str]] = [
    ("USD", "EUR"),
    ("EUR", "USD"),
]


# ---------------------------------------------------------------------------
# API call
# ---------------------------------------------------------------------------

def _fetch_from_api(from_currency: str, to_currency: str) -> Optional[float]:
    """
    Call exchangerate-api.com for the current conversion rate.
    Returns None if API key is missing or request fails.
    """
    api_key = config.EXCHANGE_RATE_API_KEY
    if not api_key:
        logger.warning(
            "EXCHANGE_RATE_API_KEY not set — cannot fetch live rates. "
            "Add it to .env: get a free key at https://www.exchangerate-api.com/"
        )
        return None

    url = _API_URL.format(
        key=api_key,
        from_c=from_currency.upper(),
        to_c=to_currency.upper(),
    )
    try:
        resp = requests.get(url, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if data.get("result") == "success":
            rate = data.get("conversion_rate")
            if rate:
                logger.info(
                    "API rate %s→%s = %.6f",
                    from_currency, to_currency, float(rate),
                )
                return float(rate)
        # API returned an error code (e.g. "unsupported-code", "inactive-account")
        logger.warning(
            "exchangerate-api returned non-success: %s",
            data.get("result", data),
        )
        return None
    except requests.Timeout:
        logger.warning("Exchange rate API timed out after %ds", _REQUEST_TIMEOUT)
        return None
    except requests.RequestException as exc:
        logger.warning("Exchange rate API request failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _get_cached(
    conn, rate_date: date, from_currency: str, to_currency: str
) -> Optional[float]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT rate FROM exchange_rates
            WHERE rate_date = %s
              AND from_currency = %s
              AND to_currency   = %s
            """,
            (rate_date, from_currency.upper(), to_currency.upper()),
        )
        row = cur.fetchone()
    return float(row[0]) if row else None


def _get_latest_cached(
    conn, from_currency: str, to_currency: str
) -> Optional[tuple[date, float]]:
    """Return (rate_date, rate) of the most-recent cached entry, regardless of date."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT rate_date, rate FROM exchange_rates
            WHERE from_currency = %s AND to_currency = %s
            ORDER BY rate_date DESC
            LIMIT 1
            """,
            (from_currency.upper(), to_currency.upper()),
        )
        row = cur.fetchone()
    return (row[0], float(row[1])) if row else None


def _store_rate(
    conn,
    rate_date: date,
    from_currency: str,
    to_currency: str,
    rate: float,
) -> None:
    """Upsert a rate into exchange_rates (idempotent)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO exchange_rates
                (rate_date, from_currency, to_currency, rate, fetched_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (rate_date, from_currency, to_currency)
            DO UPDATE SET rate = EXCLUDED.rate, fetched_at = NOW()
            """,
            (rate_date, from_currency.upper(), to_currency.upper(), rate),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_daily_rate(
    from_currency: str,
    to_currency: str,
    rate_date: Optional[date] = None,
) -> float:
    """
    Return the exchange rate from_currency → to_currency for rate_date.

    Fallback chain:
      1. Cache hit for the requested date  → return cached rate
      2. Fetch from exchangerate-api.com   → cache + return
      3. Most-recent cached rate           → return + log WARNING
      4. No rate at all                    → return 1.0 + log ERROR

    Args:
        from_currency: ISO 4217 code, e.g. "USD"
        to_currency:   ISO 4217 code, e.g. "EUR"
        rate_date:     Date to fetch for; defaults to today.

    Returns:
        float  e.g. 0.921500 means 1 USD = 0.9215 EUR
    """
    if rate_date is None:
        rate_date = date.today()

    # Trivial: same currency
    if from_currency.upper() == to_currency.upper():
        return 1.0

    try:
        conn = psycopg2.connect(config.POSTGRES_URL)
    except Exception as exc:
        logger.error("DB connection failed in get_daily_rate: %s", exc)
        return 1.0

    try:
        # 1. Cache hit
        cached = _get_cached(conn, rate_date, from_currency, to_currency)
        if cached is not None:
            logger.debug(
                "Cache hit %s→%s on %s = %.6f",
                from_currency, to_currency, rate_date, cached,
            )
            return cached

        # 2. Live API
        live = _fetch_from_api(from_currency, to_currency)
        if live is not None:
            _store_rate(conn, rate_date, from_currency, to_currency, live)
            return live

        # 3. Stale cache fallback
        latest = _get_latest_cached(conn, from_currency, to_currency)
        if latest is not None:
            fb_date, fb_rate = latest
            logger.warning(
                "API unavailable — using stale rate (%s) for %s→%s = %.6f",
                fb_date, from_currency, to_currency, fb_rate,
            )
            return fb_rate

        # 4. No data at all
        logger.error(
            "No exchange rate available for %s→%s on %s — defaulting to 1.0",
            from_currency, to_currency, rate_date,
        )
        return 1.0

    finally:
        conn.close()


def fetch_and_cache_today_rates() -> dict[str, float]:
    """
    Fetch today's rates for all _DAILY_PAIRS and return a summary dict.

    Called by main.py --mode fetch_exchange_rates (scheduler: 06:35 daily).
    Runs before all other pipeline pulls so the cache is warm when
    pl_processor.py needs it.

    Returns:
        dict mapping "FROM→TO" → rate
        e.g. {"USD→EUR": 0.921500, "EUR→USD": 1.084300}
    """
    today = date.today()
    logger.info("=== fetch_and_cache_today_rates | date=%s ===", today)

    results: dict[str, float] = {}
    for from_c, to_c in _DAILY_PAIRS:
        key = f"{from_c}→{to_c}"
        rate = get_daily_rate(from_c, to_c, today)
        results[key] = rate
        logger.info("%-12s = %.6f", key, rate)

    logger.info("Exchange rate fetch complete: %s", results)
    return results
