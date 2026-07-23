"""CHIP-ETF API — ETF 交叉持股分析（對標 etfcross.com）。

端點：
  GET /api/v1/etf/list            追蹤中的 ETF 主檔 + 各自最新快照
  GET /api/v1/etf/summary         首頁卡片數字（檔數 / 成分股數 / 總資金 / 情有獨鍾）
  GET /api/v1/etf/cross           交集表矩陣（成分股 × ETF）
  GET /api/v1/etf/stock/{代號}     單一成分股被哪些 ETF 持有（「持有ETF」功能亦用此支）
  GET /api/v1/etf/solo            情有獨鍾（只被單一 ETF 持有）

設計重點：各投信「基準日」不一致（國外成分股 ETF 會落後 1~3 日），故一律取
「每檔 ETF 自己的最新快照」，不做跨 ETF 同日 JOIN，否則會整批對不上。
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db

router = APIRouter(prefix="/api/v1", tags=["etf"])

# 頁面路由不掛 /api/v1 前綴（比照 market_margin 的 /margin 儀表板做法）
page_router = APIRouter(tags=["etf-page"])
_HTML = Path(__file__).resolve().parents[2] / "static" / "etf_dashboard.html"


@page_router.get("/etf", response_class=HTMLResponse)
def etf_dashboard():
    """ETF 交集表儀表板（同源讀 /api/v1/etf/*，免 CORS）。"""
    return HTMLResponse(_HTML.read_text(encoding="utf-8"))

# 每檔 ETF 的最新快照 + 每檔股票的最新收盤（價格日可能與持股基準日差一兩天，取最新即可）
_SNAP_CTE = """
WITH latest AS (
    SELECT etf_id, MAX(date) AS d FROM etf_holdings GROUP BY etf_id
),
snap AS (
    SELECT h.* FROM etf_holdings h
    JOIN latest l ON l.etf_id = h.etf_id AND l.d = h.date
),
px AS (
    SELECT stock_id, close, avg_price, high, low, date AS price_date,
           ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY date DESC) AS rn
    FROM raw_stock_price
)
"""


def _clean(name: str | None) -> str:
    """各投信回報的股票名稱含全形/半形空格（『順　達』vs『順達』），統一去空白。"""
    return re.sub(r"\s+", "", str(name or ""))


_TW_CODE = re.compile(r"^\d{4,6}[A-Z]?$")  # 台股代號（相容 00400A）

# CHIP 的 stocks.industry 存的是 TWSE 產業別「代碼」，顯示要轉中文（上櫃股此欄為空）
_INDUSTRY = {
    "01": "水泥", "02": "食品", "03": "塑膠", "04": "紡織纖維", "05": "電機機械",
    "06": "電器電纜", "08": "玻璃陶瓷", "09": "造紙", "10": "鋼鐵", "11": "橡膠",
    "12": "汽車", "14": "建材營造", "15": "航運", "16": "觀光餐旅", "17": "金融保險",
    "18": "貿易百貨", "19": "綜合", "20": "其他", "21": "化學", "22": "生技醫療",
    "23": "油電燃氣", "24": "半導體", "25": "電腦及週邊", "26": "光電", "27": "通信網路",
    "28": "電子零組件", "29": "電子通路", "30": "資訊服務", "31": "其他電子",
    "32": "文化創意", "33": "農業科技", "34": "電子商務", "35": "綠能環保",
    "36": "數位雲端", "37": "運動休閒", "38": "居家生活",
}


def _rows(db: Session, tw_only: bool) -> list[dict]:
    """取出目前快照的所有持股（含收盤價、市值、產業）。

    注意：篩選條件是「**成分股**是否為台股」，不是「ETF 是否國內型」——
    國外成分股 ETF（00988A/00990A）同樣持有台股（如 2330），對標站也把它們
    算進涵蓋卡片數，用 ETF 別過濾會少算。
    """
    sql = _SNAP_CTE + """
    SELECT s.etf_id, s.stock_id, s.stock_name, s.shares, s.weight, s.date,
           p.close, p.avg_price, p.high, p.low,
           st.industry AS industry_code, st.name AS official_name
    FROM snap s
    LEFT JOIN px p ON p.stock_id = s.stock_id AND p.rn = 1
    LEFT JOIN stocks st ON st.stock_id = s.stock_id
    """
    out = []
    for r in db.execute(text(sql)).mappings().all():
        d = dict(r)
        if tw_only and not _TW_CODE.match(str(d["stock_id"] or "")):
            continue
        # 顯示名優先用 CHIP stocks 的官方簡稱（台積電），投信自報的可能是全稱（台灣積體）
        d["stock_name"] = _clean(d.get("official_name")) or _clean(d["stock_name"])
        d["industry"] = _INDUSTRY.get(str(d.get("industry_code") or "").strip())
        d["amount"] = (d["shares"] or 0) * d["close"] if d.get("close") else None
        d["lots"] = round((d["shares"] or 0) / 1000)  # 總張數
        out.append(d)
    return out


@router.get("/etf/list")
def etf_list(db: Session = Depends(get_db)):
    """追蹤中的 ETF 主檔，附各自最新快照日期與持股檔數。"""
    sql = """
    SELECT i.etf_id, i.name, i.issuer, i.category, i.is_active, i.is_domestic,
           i.engine, i.pcf_url,
           (SELECT MAX(date) FROM etf_holdings h WHERE h.etf_id = i.etf_id) AS last_date,
           (SELECT COUNT(*) FROM etf_holdings h
             WHERE h.etf_id = i.etf_id
               AND h.date = (SELECT MAX(date) FROM etf_holdings x WHERE x.etf_id = i.etf_id)
           ) AS n_holdings
    FROM etf_info i ORDER BY i.is_active, i.etf_id
    """
    return {"etfs": [dict(r) for r in db.execute(text(sql)).mappings().all()]}


@router.get("/etf/summary")
def etf_summary(tw_only: bool = Query(True, description="只計台股成分股"),
                db: Session = Depends(get_db)):
    """首頁卡片數字（對應對標站的：情有獨鍾／顯示成份股／最高涵蓋數／涉及總資金）。"""
    rows = _rows(db, tw_only)
    by_stock: dict[str, set] = {}
    for r in rows:
        by_stock.setdefault(r["stock_id"], set()).add(r["etf_id"])
    top = max(by_stock.items(), key=lambda kv: len(kv[1]), default=(None, set()))
    return {
        "etf_count": len({r["etf_id"] for r in rows}),
        "etf_total": db.execute(text("SELECT COUNT(*) FROM etf_info")).scalar(),
        "stock_count": len(by_stock),
        "solo_count": sum(1 for v in by_stock.values() if len(v) == 1),
        "total_amount": sum(r["amount"] or 0 for r in rows),
        "max_cover": len(top[1]),
        "max_cover_stock": top[0],
        "last_update": max((str(r["date"]) for r in rows), default=None),
        "tw_only": tw_only,
    }


@router.get("/etf/cross")
def etf_cross(min_etf: int = Query(1, ge=1, description="至少被幾檔 ETF 持有"),
              tw_only: bool = Query(True),
              limit: int = Query(300, ge=1, le=2000),
              db: Session = Depends(get_db)):
    """交集表矩陣：每檔成分股 × 持有它的 ETF（含權重/股數），加聚合欄位。"""
    rows = _rows(db, tw_only)
    etfs: dict[str, dict] = {}
    for r in db.execute(text("SELECT etf_id, name, issuer, is_active FROM etf_info")).mappings():
        etfs[r["etf_id"]] = dict(r)

    agg: dict[str, dict] = {}
    for r in rows:
        a = agg.setdefault(r["stock_id"], {
            "stock_id": r["stock_id"], "stock_name": r["stock_name"],
            "industry": r.get("industry"),
            "n_etf": 0, "max_weight": 0.0, "total_amount": 0.0, "total_lots": 0,
            "holdings": {},
        })
        # 無官方簡稱時（多為上櫃股），各投信自報名長短不一，取最短的當顯示名
        if r["stock_name"] and (not a["stock_name"] or len(r["stock_name"]) < len(a["stock_name"])):
            a["stock_name"] = r["stock_name"]
        if not a["industry"] and r.get("industry"):
            a["industry"] = r["industry"]
        a["n_etf"] += 1
        a["max_weight"] = max(a["max_weight"], r["weight"] or 0)
        a["total_amount"] += r["amount"] or 0
        a["total_lots"] += r["lots"] or 0
        a["holdings"][r["etf_id"]] = {"weight": r["weight"], "shares": r["shares"],
                                      "lots": r["lots"], "amount": r["amount"]}
    out = [a for a in agg.values() if a["n_etf"] >= min_etf]
    out.sort(key=lambda x: (-x["n_etf"], -x["total_amount"]))
    used = sorted({e for a in out for e in a["holdings"]},
                  key=lambda e: (etfs.get(e, {}).get("is_active", 0), e))
    return {
        "etfs": [etfs.get(e, {"etf_id": e}) for e in used],
        "rows": out[:limit],
        "total": len(out),
    }


@router.get("/etf/stock/{stock_id}")
def etf_by_stock(stock_id: str, db: Session = Depends(get_db)):
    """這檔股票被哪些 ETF 持有 —— PYCHARTs「持有ETF」分頁的資料來源。"""
    sql = _SNAP_CTE + """
    SELECT s.etf_id, i.name AS etf_name, i.issuer, i.is_active,
           s.shares, s.weight, s.date, p.close
    FROM snap s
    JOIN etf_info i ON i.etf_id = s.etf_id
    LEFT JOIN px p ON p.stock_id = s.stock_id AND p.rn = 1
    WHERE s.stock_id = :sid
    ORDER BY s.weight DESC
    """
    held = []
    for r in db.execute(text(sql), {"sid": stock_id}).mappings().all():
        d = dict(r)
        d["amount"] = (d["shares"] or 0) * d["close"] if d.get("close") else None
        held.append(d)
    return {
        "stock_id": stock_id,
        "n_etf": len(held),
        "total_shares": sum(h["shares"] or 0 for h in held),
        "total_amount": sum(h["amount"] or 0 for h in held),
        "etfs": held,
    }


@router.get("/etf/solo")
def etf_solo(tw_only: bool = Query(True), db: Session = Depends(get_db)):
    """情有獨鍾：只被單一 ETF 持有的成分股。"""
    rows = _rows(db, tw_only)
    agg: dict[str, list] = {}
    for r in rows:
        agg.setdefault(r["stock_id"], []).append(r)
    out = []
    for sid, rs in agg.items():
        if len(rs) != 1:
            continue
        r = rs[0]
        out.append({"stock_id": sid, "stock_name": r["stock_name"], "etf_id": r["etf_id"],
                    "weight": r["weight"], "shares": r["shares"], "amount": r["amount"]})
    out.sort(key=lambda x: -(x["amount"] or 0))
    return {"total": len(out), "rows": out}
