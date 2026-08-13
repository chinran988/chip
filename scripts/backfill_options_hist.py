# -*- coding: utf-8 -*-
"""選擇權歷史 strike 塌陷修復（一次性，2026-08-13）。

背景：v0.14 前 taifex_options 用 int() 解析履約價，個股選擇權小數履約價
（17.5 等）全塌成 strike=0——每日 ~376 筆真實列互覆成 ~77 筆殘骸，
受損 2026-06-26 ~ 2026-08-12 共 33 交易日、638 個 (date,contract) 組合。

修法：TAIFEX 官網查詢頁 optDailyMarketReport（POST queryDate，歷史可查）
逐組合重抓 → 解析 20 欄 HTML 表 → 對映 raw_options_chain → 新碼 upsert
（小數各自成列）→ 該組合修復成功才刪其 strike=0 殘骸（使用者已批准覆蓋）。

用法：cd CHIP/backend && .venv/Scripts/python.exe -X utf8 ../scripts/backfill_options_hist.py
"""
import io
import re
import sys
import time
import sqlite3
from datetime import date, datetime

import requests
import pandas as pd

sys.path.insert(0, r"C:\Users\Inspiration\Documents\Project Quant\CHIP\backend")
from app.core.database import SessionLocal          # noqa: E402
from app.models.raw import RawOptionsChain           # noqa: E402
from app.collectors.taifex_options import TaifexOptionsCollector  # noqa: E402

DB = r"C:/Users/Inspiration/Documents/Project Quant/CHIP/data/chip.db"
URL = "https://www.taifex.com.tw/cht/3/optDailyMarketReport"
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
     "Referer": URL, "Content-Type": "application/x-www-form-urlencoded"}

def _f(v):
    s = str(v).replace(",", "").strip()
    if s in ("-", "", "nan", "None"): return None
    try: return float(s)
    except ValueError: return None

def _i(v):
    x = _f(v)
    return int(x) if x is not None else 0

def _expiry(v):
    # 202607.0 → '202607'；週別如 202607W2 保留原樣
    s = str(v).strip()
    return re.sub(r"\.0$", "", s)

def fetch_day_contract(iso: str, cid: str) -> list[dict] | None:
    """回 rows 或 None(查無資料)。含日期防呆：回應須含查詢日。"""
    qd = iso.replace("-", "/")
    r = requests.post(URL, data={"queryType": "2", "marketCode": "0",
                                 "commodity_id": cid, "queryDate": qd,
                                 "MarketCode": "0", "commodity_idt": cid},
                      headers=H, timeout=60)
    r.raise_for_status()
    if qd not in r.text:            # 日期防呆
        return None
    if "履約價" not in r.text:       # 該日該契約無資料
        return None
    t = pd.read_html(io.StringIO(r.text))[0]
    d = date.fromisoformat(iso)
    rows = []
    for _, x in t.iterrows():
        cp_raw = str(x.iloc[4]).strip()
        cp = "買權" if cp_raw.lower() == "call" else ("賣權" if cp_raw.lower() == "put" else None)
        if cp is None: continue
        strike = _f(x.iloc[3])
        if strike is None: continue
        rows.append({
            "date": d, "contract": str(x.iloc[0]).strip(),
            "expiry": _expiry(x.iloc[1]), "strike": round(strike, 2),
            "call_put": cp, "trading_session": "一般",
            "open": _f(x.iloc[5]), "high": _f(x.iloc[6]), "low": _f(x.iloc[7]),
            "close": _f(x.iloc[8]), "volume": _i(x.iloc[13]),        # *一般交易時段成交量
            "settlement_price": _f(x.iloc[9]),
            "open_interest": _i(x.iloc[15]),                          # *未沖銷契約量
            "best_bid": _f(x.iloc[16]), "best_ask": _f(x.iloc[17]),
        })
    return rows

def main():
    conn = sqlite3.connect(DB)
    pairs = conn.execute(
        "SELECT DISTINCT date, contract FROM raw_options_chain WHERE strike=0 "
        "ORDER BY date, contract").fetchall()
    conn.close()
    print(f"{datetime.now():%H:%M:%S} 受損組合 {len(pairs)} 個，開始", flush=True)

    db = SessionLocal()
    coll = TaifexOptionsCollector(db)
    ok = skip = fail = del_rows = 0
    for n, (iso, cid) in enumerate(pairs, 1):
        try:
            rows = fetch_day_contract(iso, cid)
            if rows:
                coll.upsert(RawOptionsChain, rows,
                            ["date", "contract", "expiry", "strike", "call_put", "trading_session"])
                # 修復成功 → 刪該組合殘骸（使用者批准）
                res = db.execute(
                    __import__("sqlalchemy").text(
                        "DELETE FROM raw_options_chain WHERE date=:d AND contract=:c AND strike=0"),
                    {"d": iso, "c": cid})
                del_rows += res.rowcount
                db.commit()
                ok += 1
            else:
                skip += 1     # 查無資料：殘骸保留，收尾清點
        except Exception as e:
            db.rollback()
            fail += 1
            print(f"  FAIL {iso} {cid}: {str(e)[:80]}", flush=True)
        if n % 25 == 0:
            print(f"{datetime.now():%H:%M:%S} {n}/{len(pairs)} ok={ok} skip={skip} fail={fail} 刪殘骸={del_rows}", flush=True)
        time.sleep(2.0 + (n % 3) * 0.5)   # 節流 2~3 秒
    db.close()

    conn = sqlite3.connect(DB)
    left = conn.execute("SELECT COUNT(*) FROM raw_options_chain WHERE strike=0").fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM raw_options_chain").fetchone()[0]
    conn.close()
    print(f"{datetime.now():%H:%M:%S} 完成 ok={ok} skip={skip} fail={fail} 刪殘骸={del_rows} | 剩餘 strike=0: {left} | chain 總筆數 {total}", flush=True)

if __name__ == "__main__":
    main()
