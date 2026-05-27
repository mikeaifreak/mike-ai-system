from typing import Optional

from fastapi import APIRouter, Depends, Query

from auth import get_current_user
from db import get_conn

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/today")
def get_today(
    store_id: Optional[str] = Query(default=None, description="Filter by store_id; omit for all-store aggregate"),
    current_user: str = Depends(get_current_user),
):
    """
    Return today's P&L metrics.

    - store_id=None (default): aggregate across all stores, revenue_eur/profit_eur in EUR
    - store_id=<id>: single-store row in that store's native currency
    """
    try:
        with get_conn() as conn:
            if store_id:
                # Single-store: return the raw row in native currency
                conn.execute(
                    """
                    SELECT * FROM daily_pl
                    WHERE report_date = CURRENT_DATE AND store_id = %s
                    """,
                    (store_id,),
                )
                today = conn.fetchone()
                if today is None:
                    conn.execute(
                        """
                        SELECT * FROM daily_pl
                        WHERE report_date = CURRENT_DATE - 1 AND store_id = %s
                        """,
                        (store_id,),
                    )
                    today = conn.fetchone()

                if today is not None:
                    conn.execute(
                        """
                        SELECT * FROM daily_pl
                        WHERE report_date = %s - INTERVAL '1 day' AND store_id = %s
                        """,
                        (today["report_date"], store_id),
                    )
                else:
                    conn.execute(
                        """
                        SELECT * FROM daily_pl
                        WHERE report_date = CURRENT_DATE - 2 AND store_id = %s
                        """,
                        (store_id,),
                    )
                yesterday = conn.fetchone()

                today_data    = dict(today)    if today    else None
                yesterday_data = dict(yesterday) if yesterday else None

            else:
                # All-stores aggregate — sum revenue_eur/profit_eur across stores
                conn.execute(
                    """
                    SELECT
                        CURRENT_DATE AS report_date,
                        SUM(revenue_eur) AS revenue,
                        SUM(profit_eur)  AS profit,
                        AVG(roas)        AS roas,
                        SUM(revenue_eur) AS revenue_eur,
                        SUM(profit_eur)  AS profit_eur,
                        'EUR'            AS currency
                    FROM daily_pl
                    WHERE report_date = CURRENT_DATE
                    """
                )
                row = conn.fetchone()
                if row is None or row["revenue"] is None:
                    conn.execute(
                        """
                        SELECT
                            CURRENT_DATE - 1 AS report_date,
                            SUM(revenue_eur) AS revenue,
                            SUM(profit_eur)  AS profit,
                            AVG(roas)        AS roas,
                            SUM(revenue_eur) AS revenue_eur,
                            SUM(profit_eur)  AS profit_eur,
                            'EUR'            AS currency
                        FROM daily_pl
                        WHERE report_date = CURRENT_DATE - 1
                        """
                    )
                    row = conn.fetchone()
                today_data = dict(row) if row and row["revenue"] is not None else None
                yesterday_data = None   # no cross-store yesterday for now

        # --- pct change helpers ---
        def pct(key):
            if today_data is None or yesterday_data is None:
                return None
            t_val = today_data.get(key)
            y_val = yesterday_data.get(key)
            if t_val is None or y_val is None or float(y_val) == 0:
                return None
            return round((float(t_val) - float(y_val)) / float(y_val) * 100, 2)

        pct_change = {
            "revenue": pct("revenue"),
            "profit":  pct("profit"),
            "roas":    pct("roas"),
        }

        # Compute active agent count (agent_runs rows started in last 24 h with status=running)
        try:
            with get_conn() as conn2:
                conn2.execute(
                    """
                    SELECT COUNT(DISTINCT agent_name) AS cnt
                    FROM agent_runs
                    WHERE started_at >= NOW() - INTERVAL '24 hours'
                    """
                )
                active_agents = conn2.fetchone()["cnt"]
        except Exception:
            active_agents = None

        return {
            "success": True,
            "data": {
                "today":         today_data,
                "yesterday":     yesterday_data,
                "pct_change":    pct_change,
                "active_agents": active_agents,
                "currency":      (today_data or {}).get("currency", "USD"),
            },
            "error": None,
        }
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


@router.get("/chart")
def get_chart(
    days: int = Query(default=30, ge=1, le=90),
    store_id: Optional[str] = Query(default=None),
    current_user: str = Depends(get_current_user),
):
    """
    Return time-series P&L data for the chart.

    - store_id=None: EUR aggregates across all stores
    - store_id=<id>: native currency for that store
    """
    try:
        with get_conn() as conn:
            if store_id:
                conn.execute(
                    """
                    SELECT report_date, revenue, profit, adspend_google, currency
                    FROM daily_pl
                    WHERE store_id = %s
                    ORDER BY report_date DESC
                    LIMIT %s
                    """,
                    (store_id, days),
                )
            else:
                # Cross-store: aggregate EUR values
                conn.execute(
                    """
                    SELECT
                        report_date,
                        SUM(revenue_eur) AS revenue,
                        SUM(profit_eur)  AS profit,
                        SUM(adspend_google) AS adspend_google,
                        'EUR' AS currency
                    FROM daily_pl
                    GROUP BY report_date
                    ORDER BY report_date DESC
                    LIMIT %s
                    """,
                    (days,),
                )
            rows = conn.fetchall()

        rows_list = [dict(r) for r in reversed(rows)]
        return {"success": True, "data": rows_list, "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
