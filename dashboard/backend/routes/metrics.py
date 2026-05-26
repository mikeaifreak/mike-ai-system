from fastapi import APIRouter, Depends, Query

from auth import get_current_user
from db import get_conn

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/today")
def get_today(current_user: str = Depends(get_current_user)):
    try:
        with get_conn() as conn:
            # Try today first
            conn.execute(
                "SELECT * FROM daily_pl WHERE report_date = CURRENT_DATE"
            )
            today = conn.fetchone()

            # Fall back to yesterday if today has no data yet
            if today is None:
                conn.execute(
                    "SELECT * FROM daily_pl WHERE report_date = CURRENT_DATE - 1"
                )
                today = conn.fetchone()

            # Always fetch the day before today's row for comparison
            if today is not None:
                conn.execute(
                    "SELECT * FROM daily_pl WHERE report_date = %s - INTERVAL '1 day'",
                    (today["report_date"],),
                )
            else:
                conn.execute(
                    "SELECT * FROM daily_pl WHERE report_date = CURRENT_DATE - 2"
                )
            yesterday = conn.fetchone()

        def pct(key):
            if today is None or yesterday is None:
                return None
            t_val = today.get(key)
            y_val = yesterday.get(key)
            if t_val is None or y_val is None or y_val == 0:
                return None
            return round((float(t_val) - float(y_val)) / float(y_val) * 100, 2)

        pct_change = {
            "revenue": pct("revenue"),
            "profit": pct("profit"),
            "roas": pct("roas"),
        }

        return {
            "success": True,
            "data": {
                "today": dict(today) if today else None,
                "yesterday": dict(yesterday) if yesterday else None,
                "pct_change": pct_change,
            },
            "error": None,
        }
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


@router.get("/chart")
def get_chart(
    days: int = Query(default=30, ge=1, le=90),
    current_user: str = Depends(get_current_user),
):
    try:
        with get_conn() as conn:
            conn.execute(
                """
                SELECT report_date, revenue, profit, adspend_google
                FROM daily_pl
                ORDER BY report_date DESC
                LIMIT %s
                """,
                (days,),
            )
            rows = conn.fetchall()

        # Reverse to chronological order (oldest first)
        rows_list = [dict(r) for r in reversed(rows)]
        return {"success": True, "data": rows_list, "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
