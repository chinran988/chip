"""交易日曆 API — 全球交易所假期 ＋ 經濟行事曆（資料源 investing.com）。

★ 資料庫刻意「獨立」於 chip.db（使用者拍板 2026-07-21）：見 app/collectors/global_calendar/db.py。
★ 命名用 global_calendar，避開既有的 collectors/trading_calendar.py 與 model TradingCalendar
  （那是「TWSE 當天是否為交易日」的布林表，與本模組無關）。
★ 頁面路由不掛 /api/v1 前綴（比照 market_margin 的 /margin、etf 的 /etf 做法）。

資料量大（假期萬筆、事件十萬筆級），前端一律按「檢視月份」分段取，不整表回傳。
"""
import datetime
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.collectors.global_calendar.db import conn
from app.collectors.global_calendar.regions import REGION_ORDER

router = APIRouter(prefix="/api/v1/calendar", tags=["calendar"])
page_router = APIRouter(tags=["calendar-page"])

_HTML = Path(__file__).resolve().parents[2] / "static" / "global_calendar.html"


@router.get("/meta")
def calendar_meta():
    """輕量統計＋市場清單（前端只需載入一次）。"""
    c = conn()
    markets = {}
    for r in c.execute("SELECT DISTINCT exchange,region,country FROM holidays"):
        markets[r["exchange"]] = {"exchange": r["exchange"], "region": r["region"], "country": r["country"]}
    rank = {reg: i for i, reg in enumerate(REGION_ORDER)}
    market_list = sorted(markets.values(), key=lambda m: (rank.get(m["region"], 99), m["exchange"]))
    hol_n = c.execute("SELECT COUNT(*) n FROM holidays").fetchone()["n"]
    evt_n = c.execute("SELECT COUNT(*) n FROM events").fetchone()["n"]
    sample = c.execute("SELECT COUNT(*) n FROM events WHERE source='sample'").fetchone()["n"]
    hr = c.execute("SELECT MIN(date) a, MAX(date) b FROM holidays").fetchone()
    er = c.execute("SELECT MIN(date) a, MAX(date) b FROM events").fetchone()
    countries = c.execute("SELECT COUNT(DISTINCT country) n FROM holidays").fetchone()["n"]
    c.close()
    return {
        "markets": market_list, "regionOrder": REGION_ORDER,
        "holidayCount": hol_n, "eventCount": evt_n, "countryCount": countries,
        "sampleEvents": sample > 0,
        "holidayRange": [hr["a"], hr["b"]], "eventRange": [er["a"], er["b"]],
    }


@router.get("/range")
def calendar_range(date_from: str | None = None, date_to: str | None = None):
    """指定區間的假期＋事件。不給區間時預設當月，避免誤抓全表。"""
    if not date_from or not date_to:
        today = datetime.date.today()
        date_from = today.replace(day=1).isoformat()
        nxt = (today.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
        date_to = (nxt - datetime.timedelta(days=1)).isoformat()
    c = conn()
    holidays = [dict(r) for r in c.execute(
        "SELECT date,country,exchange,region,name,type,close_time,open_time,note FROM holidays "
        "WHERE date>=? AND date<=? ORDER BY date", (date_from, date_to))]
    events = [dict(r) for r in c.execute(
        "SELECT date,time,country,region,importance,name,actual,forecast,previous,source "
        "FROM events WHERE date>=? AND date<=? ORDER BY date,time", (date_from, date_to))]
    c.close()
    return {"holidays": holidays, "events": events, "dateFrom": date_from, "dateTo": date_to}


@router.get("/upcoming")
def calendar_upcoming(days: int = 90, min_importance: int = 2, limit: int = 40):
    """從今天起的重點事件（儀表板右欄用）。"""
    today = datetime.date.today()
    end = (today + datetime.timedelta(days=days)).isoformat()
    c = conn()
    rows = [dict(r) for r in c.execute(
        "SELECT date,time,country,region,importance,name,forecast,previous FROM events "
        "WHERE date>=? AND date<=? AND importance>=? ORDER BY date,time LIMIT ?",
        (today.isoformat(), end, min_importance, limit))]
    c.close()
    return {"today": today.isoformat(), "events": rows}


@page_router.get("/calendar", response_class=HTMLResponse)
def calendar_page():
    """交易日曆頁（同源讀上面的 API，避 CSP；比照 /margin、/etf 做法）。"""
    return HTMLResponse(_HTML.read_text(encoding="utf-8"))
