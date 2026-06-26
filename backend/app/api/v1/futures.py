"""期貨籌碼 API — GET /api/v1/futures."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db

router = APIRouter(prefix="/api/v1", tags=["futures"])


@router.get("/futures")
def get_futures(
    days: int = Query(default=30, ge=1, le=365),
    contract: str = Query(default="TXF", description="TXF | MXF | 空字串=全部"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """期貨三大法人未平倉時序（TXF / MXF）。

    回傳每日 foreign_net / trust_net / dealer_net (long - short)。
    """
    params: dict[str, Any] = {"lim": days}
    contract_filter = ""
    if contract:
        contract_filter = "AND contract = :contract"
        params["contract"] = contract

    sql = text(f"""
        SELECT date, contract,
               foreign_long, foreign_short, foreign_long - foreign_short AS foreign_net,
               trust_long,   trust_short,   trust_long   - trust_short   AS trust_net,
               dealer_long,  dealer_short,  dealer_long  - dealer_short  AS dealer_net
        FROM   raw_futures_oi
        WHERE  expiry = 'all'
               {contract_filter}
        ORDER  BY date DESC, contract
        LIMIT  :lim
    """)
    rows = db.execute(sql, params).fetchall()

    cols = [
        "date", "contract",
        "foreign_long", "foreign_short", "foreign_net",
        "trust_long", "trust_short", "trust_net",
        "dealer_long", "dealer_short", "dealer_net",
    ]
    data = [dict(zip(cols, r)) for r in rows]
    for row in data:
        if hasattr(row["date"], "isoformat"):
            row["date"] = row["date"].isoformat()
    data.reverse()

    return {
        "contract": contract or "all",
        "days_returned": len(data),
        "data": data,
    }


@router.get("/futures/latest")
def get_futures_latest(
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """最新一日期貨三大法人未平倉快照（TXF + MXF）。"""
    sql = text("""
        SELECT contract,
               foreign_long, foreign_short, foreign_long - foreign_short AS foreign_net,
               trust_long,   trust_short,   trust_long   - trust_short   AS trust_net,
               dealer_long,  dealer_short,  dealer_long  - dealer_short  AS dealer_net,
               date
        FROM raw_futures_oi
        WHERE date = (SELECT MAX(date) FROM raw_futures_oi)
          AND expiry = 'all'
        ORDER BY contract
    """)
    rows = db.execute(sql).fetchall()
    result: dict[str, Any] = {}
    latest_date = None
    for r in rows:
        latest_date = r[10]
        result[r[0]] = {
            "foreign_long": r[1], "foreign_short": r[2], "foreign_net": r[3],
            "trust_long":   r[4], "trust_short":   r[5], "trust_net":   r[6],
            "dealer_long":  r[7], "dealer_short":  r[8], "dealer_net":  r[9],
        }
    return {
        "date": str(latest_date) if latest_date else None,
        "contracts": result,
    }
