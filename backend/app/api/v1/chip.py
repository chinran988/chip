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


@router.get("/chip/{stock_id}/brokers")
def get_brokers(
    stock_id: str,
    days: int = Query(default=60, ge=1, le=365),
    top: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """各券商分點買賣超彙總（top N 買超 / 賣超）。"""
    # Use 2× calendar days to safely cover N trading days
    since = date.today() - timedelta(days=days * 2)

    sql = text("""
        SELECT branch_id, branch_name,
               SUM(buy_volume)  AS buy_vol,
               SUM(sell_volume) AS sell_vol,
               SUM(buy_value)   AS buy_val,
               SUM(sell_value)  AS sell_val
        FROM   raw_broker_chips
        WHERE  stock_id = :sid AND date >= :since
        GROUP  BY branch_id, branch_name
        HAVING (buy_vol + sell_vol) > 0
        ORDER  BY (buy_vol - sell_vol) DESC
    """)
    rows = db.execute(sql, {"sid": stock_id, "since": since}).fetchall()

    def _fmt(r):
        bv = r[2] or 0
        sv = r[3] or 0
        bval = r[4] or 0
        sval = r[5] or 0
        return {
            "branch_id":     r[0],
            "branch_name":   r[1],
            "buy_volume":    bv,
            "sell_volume":   sv,
            "net_volume":    bv - sv,
            "buy_value_wan": round(bval / 10, 0),
            "sell_value_wan":round(sval / 10, 0),
            "net_value_wan": round((bval - sval) / 10, 0),
        }

    all_b = [_fmt(r) for r in rows]
    buyers  = [b for b in all_b if b["net_volume"] > 0][:top]
    sellers = sorted([b for b in all_b if b["net_volume"] < 0],
                     key=lambda x: x["net_volume"])[:top]
    return {"stock_id": stock_id, "days": days, "top_buyers": buyers, "top_sellers": sellers}


@router.get("/chip/{stock_id}/brokers/{branch_id}")
def get_broker_detail(
    stock_id: str,
    branch_id: str,
    days: int = Query(default=60, ge=1, le=365),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """指定券商分點每日明細（含累積庫存與損益）。"""
    since = date.today() - timedelta(days=days * 2)

    sql = text("""
        SELECT date, branch_name,
               buy_volume, sell_volume,
               buy_value,  sell_value
        FROM   raw_broker_chips
        WHERE  stock_id = :sid AND branch_id = :bid AND date >= :since
        ORDER  BY date ASC
    """)
    rows = db.execute(sql, {"sid": stock_id, "bid": branch_id, "since": since}).fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail="此券商無分點資料")

    branch_name = rows[0][1]
    data = []
    cum_inv = 0
    cum_pnl = 0.0  # 累計損益（萬），sell - buy 角度

    for r in rows:
        bv   = r[2] or 0          # buy_volume 張
        sv   = r[3] or 0          # sell_volume 張
        bval = r[4] or 0          # buy_value 千元
        sval = r[5] or 0          # sell_value 千元
        net_vol = bv - sv
        net_wan = round((bval - sval) / 10, 0)   # 買超為正（萬）
        pnl_day = (sval - bval) / 10              # 當日損益（萬），賣超為正
        cum_inv += net_vol
        cum_pnl += pnl_day

        buy_avg  = round(bval / bv, 2) if bv else 0
        sell_avg = round(sval / sv, 2) if sv else 0

        data.append({
            "date":          r[0].isoformat() if hasattr(r[0], "isoformat") else str(r[0]),
            "buy_volume":    bv,
            "sell_volume":   sv,
            "net_volume":    net_vol,
            "net_value_wan": net_wan,
            "buy_avg":       buy_avg,
            "sell_avg":      sell_avg,
            "cum_inventory": cum_inv,
            "cum_pnl_wan":   round(cum_pnl, 0),
        })

    data.reverse()  # newest first

    total_bv   = sum(r[2] or 0 for r in rows)
    total_sv   = sum(r[3] or 0 for r in rows)
    total_bval = sum(r[4] or 0 for r in rows)
    total_sval = sum(r[5] or 0 for r in rows)

    return {
        "branch_id":   branch_id,
        "branch_name": branch_name,
        "stock_id":    stock_id,
        "days":        days,
        "data":        data,
        "totals": {
            "buy_volume":     total_bv,
            "sell_volume":    total_sv,
            "net_volume":     total_bv - total_sv,
            "net_value_wan":  round((total_bval - total_sval) / 10, 0),
            "buy_value_wan":  round(total_bval / 10, 0),
            "sell_value_wan": round(total_sval / 10, 0),
            "cum_pnl_wan":    round((total_sval - total_bval) / 10, 0),
        },
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
