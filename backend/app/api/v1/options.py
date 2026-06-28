"""選擇權籌碼 REST API (port 8001)."""
from __future__ import annotations

import json
import logging
import requests
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import SessionLocal

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/options", tags=["options"])

_TAIFEX_BASE = "https://openapi.taifex.com.tw/v1"


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _latest_options_date(db: Session) -> Optional[str]:
    row = db.execute(text("SELECT MAX(date) FROM raw_options_chain")).fetchone()
    return str(row[0]) if row and row[0] else None


# ── 可用到期月份清單 ──────────────────────────────────────────────────────────

@router.get("/expiries")
def get_expiries(
    date_str: Optional[str] = Query(default=None, alias="date"),
    contract: str = Query(default="TXO"),
    db: Session = Depends(get_db),
):
    """返回指定合約的可用到期月份（週選 + 月選）。"""
    d = date_str or _latest_options_date(db)
    if not d:
        return {"date": None, "contract": contract, "expiries": []}
    rows = db.execute(
        text("""
            SELECT DISTINCT expiry FROM raw_options_chain
            WHERE date = :d AND contract = :c
            ORDER BY expiry
        """),
        {"d": d, "c": contract},
    ).fetchall()
    return {
        "date": d,
        "contract": contract,
        "expiries": [r[0] for r in rows],
    }


# ── 選擇權鏈（T字報價表原始資料）────────────────────────────────────────────

@router.get("/chain")
def get_chain(
    date_str: Optional[str] = Query(default=None, alias="date"),
    contract: str = Query(default="TXO"),
    expiry: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """返回選擇權鏈 Call/Put 雙邊行情，用於 T字報價表。"""
    d = date_str or _latest_options_date(db)
    if not d:
        return {"date": None, "contract": contract, "expiry": expiry, "rows": []}

    filters = "WHERE date = :d AND contract = :c"
    params: dict = {"d": d, "c": contract}
    if expiry:
        filters += " AND expiry = :e"
        params["e"] = expiry

    rows = db.execute(
        text(f"""
            SELECT expiry, strike, call_put,
                   open, high, low, close, volume,
                   settlement_price, open_interest, best_bid, best_ask
            FROM raw_options_chain
            {filters}
            ORDER BY expiry, strike, call_put
        """),
        params,
    ).fetchall()

    cols = ["expiry", "strike", "call_put", "open", "high", "low", "close",
            "volume", "settlement_price", "open_interest", "best_bid", "best_ask"]
    return {
        "date": d,
        "contract": contract,
        "expiry": expiry,
        "rows": [dict(zip(cols, r)) for r in rows],
    }


# ── 選擇權支撐壓力表（各履約價 OI）──────────────────────────────────────────

@router.get("/support-resistance")
def get_support_resistance(
    date_str: Optional[str] = Query(default=None, alias="date"),
    contract: str = Query(default="TXO"),
    expiry: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """各履約價 Call OI / Put OI 匯總，用於支撐壓力橫條圖。"""
    d = date_str or _latest_options_date(db)
    if not d:
        return {"date": None, "contract": contract, "data": []}

    filters = "WHERE date = :d AND contract = :c"
    params: dict = {"d": d, "c": contract}
    if expiry:
        filters += " AND expiry = :e"
        params["e"] = expiry

    rows = db.execute(
        text(f"""
            SELECT strike,
                   SUM(CASE WHEN call_put='C' THEN open_interest ELSE 0 END) AS call_oi,
                   SUM(CASE WHEN call_put='P' THEN open_interest ELSE 0 END) AS put_oi,
                   SUM(CASE WHEN call_put='C' THEN volume ELSE 0 END) AS call_vol,
                   SUM(CASE WHEN call_put='P' THEN volume ELSE 0 END) AS put_vol
            FROM raw_options_chain
            {filters}
            GROUP BY strike
            ORDER BY strike
        """),
        params,
    ).fetchall()

    data = [
        {"strike": r[0], "call_oi": r[1], "put_oi": r[2],
         "call_vol": r[3], "put_vol": r[4]}
        for r in rows
    ]
    return {"date": d, "contract": contract, "expiry": expiry, "data": data}


# ── 三大法人選擇權籌碼 ────────────────────────────────────────────────────────

@router.get("/institutional")
def get_institutional(
    date_str: Optional[str] = Query(default=None, alias="date"),
    db: Session = Depends(get_db),
):
    """三大法人選擇權 Call/Put 分計 + 期貨/選擇權合計。"""
    # Call/Put 分計
    cp_rows = db.execute(
        text("""
            SELECT date, contract_code, call_put, institution,
                   buy_vol, sell_vol, net_vol, oi_long, oi_short, oi_net
            FROM raw_options_institutional
            WHERE (:d IS NULL OR date = :d)
            ORDER BY date DESC, contract_code, call_put, institution
        """),
        {"d": date_str},
    ).fetchall()

    cp_cols = ["date", "contract_code", "call_put", "institution",
               "buy_vol", "sell_vol", "net_vol", "oi_long", "oi_short", "oi_net"]
    cp_data = [dict(zip(cp_cols, r)) for r in cp_rows]

    # 期貨/選擇權合計
    fo_rows = db.execute(
        text("""
            SELECT date, institution,
                   fut_buy_vol, opt_buy_vol, fut_sell_vol, opt_sell_vol,
                   fut_net_vol, opt_net_vol,
                   fut_oi_long, opt_oi_long, fut_oi_short, opt_oi_short,
                   fut_oi_net, opt_oi_net
            FROM raw_options_inst_fo
            WHERE (:d IS NULL OR date = :d)
            ORDER BY date DESC, institution
        """),
        {"d": date_str},
    ).fetchall()

    fo_cols = ["date", "institution",
               "fut_buy_vol", "opt_buy_vol", "fut_sell_vol", "opt_sell_vol",
               "fut_net_vol", "opt_net_vol",
               "fut_oi_long", "opt_oi_long", "fut_oi_short", "opt_oi_short",
               "fut_oi_net", "opt_oi_net"]
    fo_data = [dict(zip(fo_cols, r)) for r in fo_rows]

    latest_d = str(cp_data[0]["date"]) if cp_data else date_str
    return {"date": latest_d, "call_put": cp_data, "fut_opt": fo_data}


# ── 大額交易人選擇權未平倉 ────────────────────────────────────────────────────

@router.get("/large-traders")
def get_large_traders(
    date_str: Optional[str] = Query(default=None, alias="date"),
    contract: str = Query(default="TXO"),
    db: Session = Depends(get_db),
):
    """大額交易人 Top5 / Top10 選擇權未平倉（TXO 全部月份）。"""
    rows = db.execute(
        text("""
            SELECT date, contract, call_put, settlement_month, trader_type,
                   top5_buy, top5_sell, top10_buy, top10_sell, market_oi
            FROM raw_options_large_traders
            WHERE contract = :c
              AND (:d IS NULL OR date = :d)
            ORDER BY date DESC, call_put, settlement_month, trader_type
        """),
        {"c": contract, "d": date_str},
    ).fetchall()

    cols = ["date", "contract", "call_put", "settlement_month", "trader_type",
            "top5_buy", "top5_sell", "top10_buy", "top10_sell", "market_oi"]
    data = [dict(zip(cols, r)) for r in rows]
    latest_d = str(data[0]["date"]) if data else date_str
    return {"date": latest_d, "contract": contract, "data": data}


# ── Put/Call Ratio 趨勢 ───────────────────────────────────────────────────────

@router.get("/put-call-ratio")
def get_put_call_ratio(
    days: int = Query(default=22, ge=1, le=120),
    db: Session = Depends(get_db),
):
    """臺指選擇權 Put/Call 比歷史（最近 N 個交易日）。"""
    rows = db.execute(
        text("""
            SELECT date, put_volume, call_volume, pc_volume_ratio,
                   put_oi, call_oi, pc_oi_ratio
            FROM raw_put_call_ratio
            ORDER BY date DESC
            LIMIT :n
        """),
        {"n": days},
    ).fetchall()

    cols = ["date", "put_volume", "call_volume", "pc_volume_ratio",
            "put_oi", "call_oi", "pc_oi_ratio"]
    data = sorted(
        [dict(zip(cols, r)) for r in rows],
        key=lambda x: str(x["date"]),
    )
    return {"days": days, "data": data}


# ── 結算行情（proxy TAIFEX）─────────────────────────────────────────────────

@router.get("/settlement")
def get_settlement():
    """最近一次結算行情（proxy TAIFEX OpenAPI）。"""
    try:
        resp = requests.get(
            f"{_TAIFEX_BASE}/FinalSettlementPriceIndexOptions",
            timeout=15,
        )
        resp.raise_for_status()
        data = json.loads(resp.content.decode("utf-8"))
        return {"ok": True, "data": data if isinstance(data, list) else [data]}
    except Exception as e:
        logger.error("settlement proxy failed: %s", e)
        raise HTTPException(status_code=502, detail=f"TAIFEX proxy error: {e}")


# ── DB 最新選擇權日期 ─────────────────────────────────────────────────────────

@router.get("/latest-date")
def get_latest_date(db: Session = Depends(get_db)):
    """回傳 DB 中最新選擇權資料日期。"""
    d = _latest_options_date(db)
    return {"date": d}
