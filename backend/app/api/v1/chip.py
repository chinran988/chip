"""籌碼 API — GET /api/v1/chip/{stock_id}."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db

router = APIRouter(prefix="/api/v1", tags=["chip"])


def _db_rows_to_list(rows, columns: list[str]) -> list[dict]:
    return [dict(zip(columns, r)) for r in rows]


@router.get("/chip/{stock_id}")
def get_chip(
    stock_id: str,
    days: int = Query(default=60, ge=1, le=365, description="回傳最近 N 個交易日"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """股票籌碼時序資料。

    回傳欄位
    --------
    date              交易日
    foreign_net       外資淨買(張)
    trust_net         投信淨買(張)
    dealer_net        自營商淨買(張，自行+避險)
    total_net         三大法人合計
    foreign_streak    外資連買天數(正=連買,負=連賣)
    trust_streak      投信連買天數
    margin_balance    融資餘額(張)
    short_balance     融券餘額(張)
    margin_change     融資餘額日變化
    short_change      融券餘額日變化
    margin_ratio      融資佔比 % (融資/(融資+融券)×100)
    """
    # Validate stock exists
    stock = db.execute(
        text("SELECT stock_id, name FROM stocks WHERE stock_id = :sid"),
        {"sid": stock_id},
    ).fetchone()
    if not stock:
        raise HTTPException(status_code=404, detail=f"股票 {stock_id} 不存在")

    # Chip time series
    sql = text("""
        SELECT date, foreign_net, trust_net, dealer_net, total_net,
               foreign_streak, trust_streak,
               margin_balance, short_balance,
               margin_change, short_change, margin_ratio
        FROM   processed_chip
        WHERE  stock_id = :sid
        ORDER  BY date DESC
        LIMIT  :lim
    """)
    rows = db.execute(sql, {"sid": stock_id, "lim": days}).fetchall()

    chip_cols = [
        "date", "foreign_net", "trust_net", "dealer_net", "total_net",
        "foreign_streak", "trust_streak",
        "margin_balance", "short_balance",
        "margin_change", "short_change", "margin_ratio",
    ]
    data = _db_rows_to_list(rows, chip_cols)
    # Convert date objects to string
    for row in data:
        if hasattr(row["date"], "isoformat"):
            row["date"] = row["date"].isoformat()
    # Return chronological order
    data.reverse()

    # Latest futures OI (most recent date available)
    fut_sql = text("""
        SELECT contract, expiry, foreign_long, foreign_short,
               trust_long, trust_short, dealer_long, dealer_short
        FROM   raw_futures_oi
        WHERE  date = (SELECT MAX(date) FROM raw_futures_oi)
        ORDER  BY contract
    """)
    fut_rows = db.execute(fut_sql).fetchall()
    futures: dict[str, dict] = {}
    for r in fut_rows:
        contract = r[0]
        futures[contract] = {
            "foreign_long":  r[2],
            "foreign_short": r[3],
            "foreign_net":   r[2] - r[3],
            "trust_long":    r[4],
            "trust_short":   r[5],
            "trust_net":     r[4] - r[5],
            "dealer_long":   r[6],
            "dealer_short":  r[7],
            "dealer_net":    r[6] - r[7],
        }

    return {
        "stock_id": stock[0],
        "name": stock[1],
        "days_returned": len(data),
        "data": data,
        "latest_futures": futures,
    }


@router.get("/chip/{stock_id}/summary")
def get_chip_summary(
    stock_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """最新一日籌碼快照。"""
    stock = db.execute(
        text("SELECT stock_id, name FROM stocks WHERE stock_id = :sid"),
        {"sid": stock_id},
    ).fetchone()
    if not stock:
        raise HTTPException(status_code=404, detail=f"股票 {stock_id} 不存在")

    row = db.execute(
        text("""
            SELECT date, foreign_net, trust_net, dealer_net, total_net,
                   foreign_streak, trust_streak,
                   margin_balance, short_balance, margin_ratio
            FROM processed_chip
            WHERE stock_id = :sid
            ORDER BY date DESC LIMIT 1
        """),
        {"sid": stock_id},
    ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"股票 {stock_id} 尚無處理過的籌碼資料")

    return {
        "stock_id": stock[0],
        "name": stock[1],
        "date": row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0]),
        "foreign_net": row[1],
        "trust_net": row[2],
        "dealer_net": row[3],
        "total_net": row[4],
        "foreign_streak": row[5],
        "trust_streak": row[6],
        "margin_balance": row[7],
        "short_balance": row[8],
        "margin_ratio": row[9],
    }
