from fastapi import APIRouter, Depends

from auth import get_current_user
from db import get_conn

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/mtd")
def get_mtd(current_user: str = Depends(get_current_user)):
    try:
        with get_conn() as conn:
            conn.execute("SELECT * FROM mtd_summary")
            summary = conn.fetchone()

            conn.execute(
                """
                SELECT COUNT(*) AS days_in_month
                FROM generate_series(
                    DATE_TRUNC('month', CURRENT_DATE),
                    CURRENT_DATE,
                    '1 day'::interval
                )
                """
            )
            days_row = conn.fetchone()

        data = dict(summary) if summary else {}
        data["days_in_month"] = days_row["days_in_month"] if days_row else None

        return {"success": True, "data": data, "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


@router.get("/weekly")
def get_weekly(current_user: str = Depends(get_current_user)):
    try:
        with get_conn() as conn:
            conn.execute(
                """
                SELECT * FROM weekly_summary
                ORDER BY iso_year DESC, iso_week DESC
                LIMIT 12
                """
            )
            rows = [dict(r) for r in conn.fetchall()]

        return {"success": True, "data": rows, "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


@router.get("/monthly")
def get_monthly(current_user: str = Depends(get_current_user)):
    try:
        with get_conn() as conn:
            conn.execute(
                """
                SELECT * FROM monthly_summary
                ORDER BY year DESC, month DESC
                LIMIT 12
                """
            )
            rows = [dict(r) for r in conn.fetchall()]

        return {"success": True, "data": rows, "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
