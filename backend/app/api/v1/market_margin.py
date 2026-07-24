"""整體融資維持率 API — GET /api/v1/market-margin。

回傳市場整體融資維持率(%)與融資餘額(億)日序列，供儀表板讀取。
資料表 market_margin_daily 由 market_margin collector 每日更新 + 歷史回補。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import text

from app.core.database import get_db

router = APIRouter(tags=["market-margin"])
_HTML = Path(__file__).resolve().parents[2] / "static" / "margin_dashboard.html"


@router.get("/margin", response_class=HTMLResponse)
def margin_dashboard():
    """整體融資維持率儀表板（讀 /api/v1/market-margin，同源即時）。"""
    return HTMLResponse(_HTML.read_text(encoding="utf-8"))


@router.get("/api/v1/market-margin")
def market_margin(days: int = Query(default=0, description="只回最近 N 交易日；0=全部")):
    """回傳 [{date, ratio, balance_yi, shares, stock_count}]（舊到新）。
    balance_yi = 融資金額(仟元)/1e5 = 億元。"""
    db = next(get_db())
    try:
        sql = """
            SELECT date, maintenance_ratio, margin_amount, margin_shares, stock_count, taiex, txf
            FROM market_margin_daily ORDER BY date
        """
        rows = db.execute(text(sql)).fetchall()
    finally:
        db.close()
    data = [{
        "date": r[0],
        "ratio": r[1],
        "balance_yi": round((r[2] or 0) / 1e5, 1),
        "shares": r[3],
        "stock_count": r[4],
        "taiex": r[5],   # 大盤加權指數
        "txf": r[6],     # 台指期近月
    } for r in rows]
    if days and days > 0:
        data = data[-days:]
    return {"count": len(data), "data": data}
