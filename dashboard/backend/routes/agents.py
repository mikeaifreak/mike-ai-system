from fastapi import APIRouter, Depends, Query

from auth import get_current_user
from db import get_conn

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("/status")
def get_agent_status(current_user: str = Depends(get_current_user)):
    try:
        with get_conn() as conn:
            # Latest run per agent
            conn.execute(
                """
                SELECT DISTINCT ON (agent_name)
                    agent_name, status, started_at, finished_at,
                    duration_ms, error_message, rows_processed
                FROM agent_runs
                ORDER BY agent_name, started_at DESC
                """
            )
            latest_runs = {row["agent_name"]: dict(row) for row in conn.fetchall()}

            # Count today's runs per agent
            conn.execute(
                """
                SELECT agent_name, COUNT(*) AS today_runs
                FROM agent_runs
                WHERE started_at >= CURRENT_DATE
                GROUP BY agent_name
                """
            )
            today_counts = {row["agent_name"]: row["today_runs"] for row in conn.fetchall()}

            # Success rate over last 30 runs per agent
            conn.execute(
                """
                SELECT agent_name,
                       ROUND(
                           100.0 * SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END)
                           / COUNT(*), 1
                       ) AS success_rate
                FROM (
                    SELECT agent_name, status,
                           ROW_NUMBER() OVER (
                               PARTITION BY agent_name ORDER BY started_at DESC
                           ) AS rn
                    FROM agent_runs
                ) sub
                WHERE rn <= 30
                GROUP BY agent_name
                """
            )
            success_rates = {row["agent_name"]: row["success_rate"] for row in conn.fetchall()}

        result = []
        for name, run in latest_runs.items():
            run["today_runs"] = today_counts.get(name, 0)
            run["success_rate"] = float(success_rates.get(name, 0))
            result.append(run)

        return {"success": True, "data": result, "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


@router.get("/logs")
def get_agent_logs(
    limit: int = Query(default=20, ge=1, le=200),
    current_user: str = Depends(get_current_user),
):
    try:
        with get_conn() as conn:
            conn.execute(
                """
                SELECT id, agent_name, status, started_at, finished_at,
                       duration_ms, rows_processed, rows_inserted, rows_updated,
                       tokens_used, error_message, trigger_type
                FROM agent_runs
                ORDER BY started_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = [dict(r) for r in conn.fetchall()]

        return {"success": True, "data": rows, "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
