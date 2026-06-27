"""Admin / manual trigger endpoints (protected by API key)."""
from __future__ import annotations

import threading
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from app.core.security import verify_api_key
from app.core.database import SessionLocal

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(verify_api_key)])

# ── Backfill state (module-level, single-threaded safe for one concurrent job) ──
_backfill: dict[str, Any] = {
    "running": False,
    "start_date": "",
    "end_date": "",
    "current_date": "",
    "completed": 0,
    "total": 0,
    "errors": [],
    "done": False,
}
_backfill_lock = threading.Lock()


# ── Single-day collect helpers ────────────────────────────────────────────────

def _collect_one_day(d: date) -> dict[str, int]:
    from app.collectors.twse_institutional import InstitutionalCollector
    from app.collectors.twse_margin import MarginCollector
    from app.collectors.taifex_futures import FuturesOICollector
    from app.processors.chip_processor import ChipProcessor

    db = SessionLocal()
    results: dict[str, int] = {}
    try:
        for Cls in (InstitutionalCollector, MarginCollector, FuturesOICollector):
            col = Cls(db)
            try:
                results[col.name] = col.collect(d)
            except Exception as e:
                results[col.name] = -1
                results[f"{col.name}_err"] = str(e)[:80]
        try:
            results["processed"] = ChipProcessor(db).process(d)
        except Exception as e:
            results["processed"] = -1
            results["processed_err"] = str(e)[:80]
    finally:
        db.close()
    return results


def _trading_days_in_range(start: date, end: date) -> list[date]:
    """Return all trading days in [start, end] from trading_calendar."""
    db = SessionLocal()
    try:
        from sqlalchemy import text
        rows = db.execute(text("""
            SELECT date FROM trading_calendar
            WHERE is_trading_day = 1 AND date >= :s AND date <= :e
            ORDER BY date
        """), {"s": str(start), "e": str(end)}).fetchall()
        return [date.fromisoformat(r[0]) for r in rows]
    finally:
        db.close()


def _run_backfill(start: date, end: date) -> None:
    global _backfill
    trading_days = _trading_days_in_range(start, end)
    with _backfill_lock:
        _backfill.update({
            "running": True, "done": False, "errors": [],
            "completed": 0, "total": len(trading_days),
            "start_date": str(start), "end_date": str(end),
        })

    for d in trading_days:
        with _backfill_lock:
            _backfill["current_date"] = str(d)
        try:
            res = _collect_one_day(d)
            errs = {k: v for k, v in res.items() if k.endswith("_err")}
            if errs:
                with _backfill_lock:
                    _backfill["errors"].append({"date": str(d), **errs})
        except Exception as e:
            with _backfill_lock:
                _backfill["errors"].append({"date": str(d), "error": str(e)[:120]})
        with _backfill_lock:
            _backfill["completed"] += 1

    with _backfill_lock:
        _backfill.update({"running": False, "done": True, "current_date": ""})


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/collect/stocks")
def trigger_collect_stocks():
    from app.scheduler.jobs import job_collect_stocks
    job_collect_stocks()
    return {"ok": True, "job": "collect_stocks"}


@router.post("/collect/daily")
def trigger_daily_collect(target_date: str = Query(default=None, description="YYYY-MM-DD")):
    from app.scheduler.jobs import _today_cst
    from app.collectors.twse_institutional import InstitutionalCollector
    from app.collectors.twse_margin import MarginCollector
    from app.collectors.taifex_futures import FuturesOICollector

    d = date.fromisoformat(target_date) if target_date else _today_cst()
    db = SessionLocal()
    results = {}
    try:
        for Cls in (InstitutionalCollector, MarginCollector, FuturesOICollector):
            col = Cls(db)
            try:
                results[col.name] = col.collect(d)
            except Exception as e:
                results[col.name] = f"error: {e}"
    finally:
        db.close()
    return {"ok": True, "date": str(d), "results": results}


@router.post("/collect/calendar")
def trigger_fill_calendar(year: int = Query(default=None)):
    from app.scheduler.jobs import _today_cst
    from app.collectors.trading_calendar import TradingCalendarCollector
    db = SessionLocal()
    try:
        col = TradingCalendarCollector(db)
        y = year or _today_cst().year
        count = col.fill_year(y)
        return {"ok": True, "year": y, "days": count}
    finally:
        db.close()


@router.post("/process/chip")
def trigger_process_chip(target_date: str = Query(default=None, description="YYYY-MM-DD")):
    from app.scheduler.jobs import _today_cst
    from app.processors.chip_processor import ChipProcessor
    d = date.fromisoformat(target_date) if target_date else _today_cst()
    db = SessionLocal()
    try:
        count = ChipProcessor(db).process(d)
        return {"ok": True, "date": str(d), "rows_upserted": count}
    finally:
        db.close()


@router.post("/generate/report")
def trigger_generate_report(target_date: str = Query(default=None, description="YYYY-MM-DD")):
    from app.scheduler.jobs import _today_cst
    from app.reporters.chip_reporter import ChipReporter
    d = date.fromisoformat(target_date) if target_date else _today_cst()
    db = SessionLocal()
    try:
        fpath = ChipReporter(db).generate(d)
        return {"ok": True, "date": str(d), "file": fpath.name,
                "size_kb": round(fpath.stat().st_size / 1024, 1)}
    finally:
        db.close()


@router.post("/backfill/chip")
def trigger_backfill_chip(
    background_tasks: BackgroundTasks,
    start_date: str = Query(description="開始日期 YYYY-MM-DD"),
    end_date: str = Query(default=None, description="結束日期 YYYY-MM-DD（預設今日）"),
):
    """背景補抓指定日期範圍的三大法人/融資券/期貨OI，並自動跑 ChipProcessor。"""
    global _backfill
    with _backfill_lock:
        if _backfill["running"]:
            return {"ok": False, "error": "backfill already running",
                    "status": dict(_backfill)}

    from app.scheduler.jobs import _today_cst
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date) if end_date else _today_cst()
    if start > end:
        return {"ok": False, "error": "start_date must be <= end_date"}

    background_tasks.add_task(_run_backfill, start, end)
    return {"ok": True, "status": "started", "start_date": str(start), "end_date": str(end)}


@router.get("/backfill/chip/status")
def backfill_status():
    """查詢目前補抓進度。"""
    with _backfill_lock:
        return dict(_backfill)


@router.post("/collect/broker-chips")
def trigger_broker_chips(
    stock_ids: str = Query(description="逗號分隔股票代號，e.g. 2330,2317（上市用TWSE）"),
    target_date: str = Query(default=None),
):
    """手動觸發上市(TWSE)券商分點採集。"""
    from app.scheduler.jobs import _today_cst
    from app.collectors.twse_broker_chips import BrokerChipsCollector
    d = date.fromisoformat(target_date) if target_date else _today_cst()
    ids = [s.strip() for s in stock_ids.split(",") if s.strip()]
    db = SessionLocal()
    try:
        col = BrokerChipsCollector(db)
        count = col.collect_stocks(d, ids)
        return {"ok": True, "market": "twse", "date": str(d), "stocks": ids, "rows": count}
    finally:
        db.close()


@router.post("/collect/broker-chips/bsr")
def trigger_broker_chips_bsr(
    stock_ids: str = Query(description="逗號分隔上市股票代號，e.g. 2330,2317（BSR 每筆間隔 30 秒，請勿一次太多）"),
    target_date: str = Query(default=None),
):
    """手動觸發 BSR 買賣日報表採集（當日彙總，含成交均價）。30 秒/筆。"""
    from app.scheduler.jobs import _today_cst
    from app.collectors.bsr_broker_chips import BsrBrokerChipsCollector
    d = date.fromisoformat(target_date) if target_date else _today_cst()
    ids = [s.strip() for s in stock_ids.split(",") if s.strip()]
    db = SessionLocal()
    try:
        col = BsrBrokerChipsCollector(db)
        count = col.collect_stocks(d, ids)
        return {"ok": True, "source": "bsr", "date": str(d), "stocks": ids, "rows": count}
    finally:
        db.close()


@router.post("/collect/tpex-csv")
def receive_tpex_csv(payload: dict):
    """接收瀏覽器端 fetch 的 TPEx CSV，解析後寫入 raw_broker_chips。
    Payload: {date: "YYYY-MM-DD", code: "XXXX", csv_text: "..."}
    """
    from app.collectors.bsr_broker_chips import BsrBrokerChipsCollector
    from app.collectors.tpex_broker_chips import parse_csv_text
    from app.models.raw import RawBrokerChips

    code = str(payload.get("code", "")).strip()
    csv_text = str(payload.get("csv_text", ""))
    raw_date = str(payload.get("date", ""))
    if not code or not csv_text or not raw_date:
        return {"ok": False, "error": "missing code/csv_text/date"}
    try:
        d = date.fromisoformat(raw_date)
        rows = parse_csv_text(csv_text, d, code)
        if not rows:
            return {"ok": True, "saved": 0, "brokers": 0}
        db = SessionLocal()
        try:
            col = BsrBrokerChipsCollector(db)
            col.upsert(RawBrokerChips, rows, ["date", "stock_id", "branch_id"])
            db.commit()
            return {"ok": True, "saved": len(rows), "brokers": len(rows)}
        finally:
            db.close()
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


@router.post("/collect/broker-chips/otc")
def trigger_broker_chips_otc(
    stock_ids: str = Query(default=None, description="逗號分隔上櫃股票代號（留空=全部上櫃）"),
    target_date: str = Query(default=None),
):
    """手動觸發上櫃(TPEx)券商分點採集。"""
    from app.scheduler.jobs import _today_cst
    from app.collectors.tpex_broker_chips import TpexBrokerChipsCollector
    d = date.fromisoformat(target_date) if target_date else _today_cst()
    ids = [s.strip() for s in stock_ids.split(",") if s.strip()] if stock_ids else None
    db = SessionLocal()
    try:
        col = TpexBrokerChipsCollector(db)
        count = col.collect_stocks(d, ids)
        return {"ok": True, "market": "otc", "date": str(d),
                "stocks": ids or "all-otc", "rows": count}
    finally:
        db.close()
