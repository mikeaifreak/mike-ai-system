from fastapi import APIRouter, Depends, Query

from auth import get_current_user
from db import get_conn

router = APIRouter(prefix="/finance", tags=["finance"])

_VALID_RANGES = {"today", "7d", "30d", "mtd", "all"}

_DATE_FILTERS = {
    "today": "report_date = CURRENT_DATE",
    "7d": "report_date >= CURRENT_DATE - 7",
    "30d": "report_date >= CURRENT_DATE - 30",
    "mtd": "report_date >= DATE_TRUNC('month', CURRENT_DATE)",
    "all": None,
}

# Columns that should be summed vs averaged
_SUM_COLS = {"revenue", "adspend_google", "adspend_meta", "profit", "cogs",
             "orders", "units_sold", "refunds"}
_AVG_COLS = {"roas", "profit_pct", "aov", "cpc"}


def _compute_totals(rows: list) -> dict:
    if not rows:
        return {}

    totals: dict = {}
    if not rows:
        return totals

    all_keys = rows[0].keys()
    for key in all_keys:
        values = [r[key] for r in rows if r[key] is not None]
        if not values:
            totals[key] = None
            continue
        try:
            numeric_vals = [float(v) for v in values]
        except (TypeError, ValueError):
            totals[key] = None
            continue

        if key in _AVG_COLS:
            totals[key] = round(sum(numeric_vals) / len(numeric_vals), 4)
        elif key in _SUM_COLS:
            totals[key] = round(sum(numeric_vals), 4)
        else:
            totals[key] = None  # non-numeric aggregate not meaningful

    return totals


@router.get("/table")
def get_finance_table(
    range: str = Query(default="7d"),
    current_user: str = Depends(get_current_user),
):
    if range not in _VALID_RANGES:
        return {
            "success": False,
            "data": None,
            "error": f"Invalid range '{range}'. Valid options: {', '.join(sorted(_VALID_RANGES))}",
        }

    try:
        date_filter = _DATE_FILTERS[range]
        if date_filter:
            sql = f"SELECT * FROM daily_pl WHERE {date_filter} ORDER BY report_date DESC"
            params = ()
        else:
            sql = "SELECT * FROM daily_pl ORDER BY report_date DESC"
            params = ()

        with get_conn() as conn:
            conn.execute(sql, params)
            rows = [dict(r) for r in conn.fetchall()]

        totals = _compute_totals(rows)

        return {"success": True, "data": {"rows": rows, "totals": totals}, "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
