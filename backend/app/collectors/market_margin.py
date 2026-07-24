"""整體融資維持率 + 融資餘額（市場彙總，TWSE 官方口徑）。

維持率 = Σ(個股融資餘額張數 × 當日收盤價) ÷ 整體融資金額(仟元) × 100%
  分子：MI_MARGN tables[1] 逐檔融資今日餘額(張) × MI_INDEX tables[8] 逐檔收盤價
  分母：MI_MARGN tables[0]「融資金額(仟元)」今日餘額
已於 2026-07-17 重現官方值 170.53%（誤差 0）。

資料表 market_margin_daily：
  date / margin_shares(張) / margin_amount(仟元) / collateral_value(仟元) / maintenance_ratio / stock_count
"""
from __future__ import annotations

import json
import ssl
import urllib.request
from datetime import date

_TWSE = "https://www.twse.com.tw/exchangeReport"


def _ctx() -> ssl.SSLContext:
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(url=req, timeout=45, context=_ctx()))


def _num(s) -> float:
    try:
        return float(str(s).replace(",", "").strip() or 0)
    except (ValueError, TypeError):
        return 0.0


def ensure_table(conn) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS market_margin_daily (
            date              TEXT PRIMARY KEY,
            margin_shares     BIGINT,   -- 整體融資餘額(張)
            margin_amount     BIGINT,   -- 整體融資金額(仟元)  ← 融資餘額圖(/1e5=億)
            collateral_value  BIGINT,   -- 擔保品市值 Σ(張×收盤)(仟元)
            maintenance_ratio REAL,     -- 融資維持率(%)
            stock_count       INTEGER,  -- 配對到收盤的檔數
            created_at        TEXT DEFAULT (datetime('now'))
        )
    """)
    # 疊圖用欄位（後加，容忍已存在）
    for col, typ in (("taiex", "REAL"), ("txf", "REAL")):
        try:
            conn.execute(f"ALTER TABLE market_margin_daily ADD COLUMN {col} {typ}")
        except Exception:
            pass
    conn.commit()


def fetch_txf(d: date) -> float | None:
    """台指期(TX)近月收盤 — TAIFEX 日行情報表，可回溯歷史。"""
    import re
    import urllib.parse
    body = urllib.parse.urlencode({
        "queryType": "2", "marketCode": "0", "MarketCode": "0",
        "commodity_id": "TX", "commodity_idt": "TX",
        "queryDate": d.strftime("%Y/%m/%d"),
    }).encode()
    req = urllib.request.Request(
        "https://www.taifex.com.tw/cht/3/futDailyMarketReport", data=body,
        headers={"User-Agent": "Mozilla/5.0",
                 "Content-Type": "application/x-www-form-urlencoded"})
    html = urllib.request.urlopen(req, timeout=45, context=_ctx()).read().decode("utf-8", "ignore")
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = [re.sub(r"<[^>]+>", "", x).strip()
                 for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        # 近月：第一列 TX + 純數字到期月份（排除價差列 202006/202007）
        if len(cells) >= 6 and cells[0] == "TX" and cells[1].isdigit():
            v = _num(cells[5])          # 收盤價
            return v or None
    return None


def compute_day(d: date) -> dict | None:
    """回傳當日彙總；若非交易日（API 無資料）回 None。"""
    ymd = d.strftime("%Y%m%d")
    mg = _get(f"{_TWSE}/MI_MARGN?response=json&date={ymd}&selectType=ALL")
    if mg.get("stat") != "OK" or len(mg.get("tables", [])) < 2:
        return None
    t0 = mg["tables"][0]
    amount = shares = None
    for row in t0.get("data", []):
        label = str(row[0])
        if "融資金額" in label:
            amount = _num(row[5])                 # 今日餘額(仟元)
        elif "融資" in label and "交易單位" in label:
            shares = _num(row[5])                 # 今日餘額(張)
    if not amount:
        return None
    # 逐檔融資今日餘額(張)
    per = {}
    for row in mg["tables"][1].get("data", []):
        sid = str(row[0]).strip()
        if sid:
            per[sid] = _num(row[6])

    # 逐檔收盤 + 大盤加權指數（同一支 MI_INDEX）
    mi = _get(f"{_TWSE}/MI_INDEX?response=json&date={ymd}&type=ALLBUT0999")
    close = {}
    taiex = None
    for t in mi.get("tables", []):
        flds = t.get("fields", [])
        if len(t.get("data", [])) > 500 and "收盤價" in flds:
            ci = flds.index("收盤價")
            for row in t["data"]:
                close[str(row[0]).strip()] = _num(row[ci])
        elif taiex is None and "收盤指數" in flds:
            ci2 = flds.index("收盤指數")
            for row in t.get("data", []):
                # 精確抓「發行量加權股價指數」(價格指數)，排除「…報酬指數」
                if str(row[0]).strip() == "發行量加權股價指數":
                    taiex = _num(row[ci2])
                    break

    numer = 0.0  # Σ(張×收盤) = 仟元
    matched = 0
    for sid, sh in per.items():
        p = close.get(sid)
        if p and sh > 0:
            numer += sh * p
            matched += 1
    if matched == 0:
        return None
    ratio = numer / amount * 100
    try:
        txf = fetch_txf(d)
    except Exception:
        txf = None
    return {
        "date": d.isoformat(),
        "margin_shares": int(shares or 0),
        "margin_amount": int(amount),
        "collateral_value": int(numer),
        "maintenance_ratio": round(ratio, 2),
        "stock_count": matched,
        "taiex": taiex,
        "txf": txf,
    }


def store_day(conn, rec: dict) -> None:
    conn.execute("""
        INSERT INTO market_margin_daily
          (date, margin_shares, margin_amount, collateral_value, maintenance_ratio, stock_count, taiex, txf)
        VALUES (:date,:margin_shares,:margin_amount,:collateral_value,:maintenance_ratio,:stock_count,:taiex,:txf)
        ON CONFLICT(date) DO UPDATE SET
          margin_shares=excluded.margin_shares,
          margin_amount=excluded.margin_amount,
          collateral_value=excluded.collateral_value,
          maintenance_ratio=excluded.maintenance_ratio,
          stock_count=excluded.stock_count,
          taiex=COALESCE(excluded.taiex, market_margin_daily.taiex),
          txf=COALESCE(excluded.txf, market_margin_daily.txf)
    """, rec)
    conn.commit()
