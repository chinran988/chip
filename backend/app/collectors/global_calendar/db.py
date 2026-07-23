"""SQLite 儲存層 — 交易日曆專用的獨立資料庫 data/calendar.db。

刻意不併入 chip.db：CHIP 的 SQLAlchemy 層綁死單一 settings.db_path，本模組沿用 raw sqlite3
自帶路徑（CHIP 既有先例：collectors/market_margin.py）。"""
import os
import pathlib
import sqlite3

# CHIP 專案根（本檔位於 backend/app/collectors/global_calendar/）
_CHIP_ROOT = pathlib.Path(__file__).resolve().parents[4]
# 日曆使用「獨立」資料庫，刻意不併入 chip.db（使用者拍板 2026-07-21）；可用 CALENDAR_DB 覆寫
DB_PATH = pathlib.Path(os.environ.get("CALENDAR_DB") or (_CHIP_ROOT / "data" / "calendar.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS holidays (
    date       TEXT NOT NULL,        -- YYYY-MM-DD
    country    TEXT NOT NULL,
    exchange   TEXT NOT NULL,
    region     TEXT,
    name       TEXT NOT NULL,        -- 假日名
    type       TEXT NOT NULL DEFAULT '休市',   -- 休市 / 早收
    close_time TEXT,                 -- 早收時間（台灣時間，如「4/3(五) 21:15 夏令」）；investing 無此資料
    open_time  TEXT,                 -- 開盤/恢復交易時間（台灣時間）
    note       TEXT,                 -- 備註（商品別、公告異動等）
    source     TEXT NOT NULL DEFAULT 'investing',
    scraped_at TEXT,
    PRIMARY KEY (date, exchange, name)
);
CREATE INDEX IF NOT EXISTS idx_hol_date ON holidays(date);

CREATE TABLE IF NOT EXISTS events (
    date       TEXT NOT NULL,        -- YYYY-MM-DD
    time       TEXT,                 -- HH:MM (GMT+8) 或 空
    country    TEXT NOT NULL,
    region     TEXT,
    importance INTEGER DEFAULT 0,    -- 1..3
    name       TEXT NOT NULL,
    actual     TEXT, forecast TEXT, previous TEXT,
    source     TEXT NOT NULL DEFAULT 'investing',
    scraped_at TEXT,
    PRIMARY KEY (date, country, name, time)
);
CREATE INDEX IF NOT EXISTS idx_evt_date ON events(date);

CREATE TABLE IF NOT EXISTS scrape_log (
    ts TEXT, kind TEXT, ok INTEGER, rows INTEGER, note TEXT
);

-- 分階段爬取的續傳狀態：已完成的日期區塊不再重抓
CREATE TABLE IF NOT EXISTS scrape_ranges (
    kind TEXT, date_from TEXT, date_to TEXT, rows INTEGER, ok INTEGER, ts TEXT,
    PRIMARY KEY (kind, date_from, date_to)
);
"""


def range_done(c, kind, df, dt):
    return c.execute(
        "SELECT 1 FROM scrape_ranges WHERE kind=? AND date_from=? AND date_to=? AND ok=1",
        (kind, df, dt),
    ).fetchone() is not None


def mark_range(c, kind, df, dt, rows, ok):
    c.execute(
        "INSERT OR REPLACE INTO scrape_ranges(kind,date_from,date_to,rows,ok,ts) VALUES(?,?,?,?,?,datetime('now'))",
        (kind, df, dt, rows, 1 if ok else 0),
    )


def _ensure_columns(c):
    """既有 DB 自動遷移：補上後來新增的欄位（SQLite 無 ADD COLUMN IF NOT EXISTS）。"""
    have = {r[1] for r in c.execute("PRAGMA table_info(holidays)")}
    for col in ("close_time", "open_time", "note"):
        if col not in have:
            c.execute(f"ALTER TABLE holidays ADD COLUMN {col} TEXT")


def conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    _ensure_columns(c)
    return c


def upsert_holidays(c, rows, scraped_at):
    payload = [{
        "close_time": None, "open_time": None, "note": None,
        **r, "scraped_at": scraped_at, "source": r.get("source", "investing"),
    } for r in rows]
    c.executemany(
        """INSERT OR REPLACE INTO holidays
           (date,country,exchange,region,name,type,close_time,open_time,note,source,scraped_at)
           VALUES (:date,:country,:exchange,:region,:name,:type,:close_time,:open_time,:note,:source,:scraped_at)""",
        payload,
    )
    return len(rows)


def upsert_events(c, rows, scraped_at):
    payload = [{**r, "scraped_at": scraped_at, "source": r.get("source", "investing")} for r in rows]
    c.executemany(
        """INSERT OR REPLACE INTO events
           (date,time,country,region,importance,name,actual,forecast,previous,source,scraped_at)
           VALUES (:date,:time,:country,:region,:importance,:name,:actual,:forecast,:previous,:source,:scraped_at)""",
        payload,
    )
    return len(rows)


def log(c, kind, ok, rows, note=""):
    c.execute("INSERT INTO scrape_log(ts,kind,ok,rows,note) VALUES(datetime('now'),?,?,?,?)",
              (kind, 1 if ok else 0, rows, note))
