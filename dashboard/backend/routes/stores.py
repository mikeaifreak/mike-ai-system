"""
stores.py — REST endpoints for the stores master config table.

GET /stores/list
    Returns all active stores with their store_id, display_name, and currency.
    Used by the Dashboard frontend to populate the store selector dropdown
    and determine which currency symbol to display.
"""

from fastapi import APIRouter, Depends

from auth import get_current_user
from db import get_conn

router = APIRouter(prefix="/stores", tags=["stores"])


@router.get("/list")
def list_stores(current_user: str = Depends(get_current_user)):
    """
    Return all active stores ordered by display_name.
    Guaranteed to return at least the 'default' store (seeded by schema.sql).
    """
    try:
        with get_conn() as conn:
            conn.execute(
                """
                SELECT store_id, display_name, currency, is_active
                FROM stores
                WHERE is_active = TRUE
                ORDER BY display_name
                """
            )
            rows = conn.fetchall()

        stores = [dict(r) for r in rows]

        # Ensure the default store is always present even if the table is empty
        if not stores:
            stores = [{"store_id": "default", "display_name": "FRUGAZE", "currency": "USD", "is_active": True}]

        return {"success": True, "data": stores, "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
