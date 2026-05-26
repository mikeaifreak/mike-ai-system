from fastapi import APIRouter, Depends, Query

from auth import get_current_user
from db import get_conn

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("/recent")
def get_recent_alerts(
    limit: int = Query(default=8, ge=1, le=100),
    current_user: str = Depends(get_current_user),
):
    try:
        with get_conn() as conn:
            conn.execute(
                """
                SELECT id, alert_type, channel, recipient, trigger_metric,
                       trigger_value, message_preview, delivered, sent_at
                FROM alerts_log
                ORDER BY sent_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = [dict(r) for r in conn.fetchall()]

        return {"success": True, "data": rows, "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
