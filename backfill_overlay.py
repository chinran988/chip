"""回補疊圖欄位：大盤加權指數(taiex) + 台指期近月(txf)。
只更新 market_margin_daily 既有列中 taiex/txf 為空者；2 支 API/日，節流防限流、可續跑。
用法：python backfill_overlay.py
"""
import sys, os, time, sqlite3, datetime, random, json, urllib.request, ssl

BACKEND = r"C:\Users\Inspiration\Documents\Project Quant\CHIP\backend"
DB      = r"C:\Users\Inspiration\Documents\Project Quant\CHIP\data\chip.db"
LOG     = os.path.join(os.environ.get("TEMP", r"C:\Users\INSPIR~1\AppData\Local\Temp"), "overlay_backfill.log")
sys.path.insert(0, BACKEND); os.chdir(BACKEND)
os.environ.setdefault("PYTHONUTF8", "1")
from app.collectors import market_margin as mm


def log(msg):
    line = f"[{datetime.datetime.now():%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def fetch_taiex(d):
    ymd = d.strftime("%Y%m%d")
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    url = f"https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&date={ymd}&type=ALLBUT0999"
    j = json.load(urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=45, context=ctx))
    for t in j.get("tables", []):
        flds = t.get("fields", [])
        if "收盤指數" in flds:
            ci = flds.index("收盤指數")
            for row in t.get("data", []):
                if str(row[0]).strip() == "發行量加權股價指數":   # 價格指數，非報酬指數
                    return mm._num(row[ci])
    return None


def main():
    conn = sqlite3.connect(DB)
    mm.ensure_table(conn)
    rows = conn.execute(
        "SELECT date FROM market_margin_daily WHERE taiex IS NULL OR txf IS NULL ORDER BY date"
    ).fetchall()
    days = [datetime.date.fromisoformat(r[0]) for r in rows]
    log(f"===== 疊圖回補開始，待補 {len(days)} 天 =====")

    ok = fail = 0
    for i, d in enumerate(days):
        taiex = txf = None
        try:
            taiex = fetch_taiex(d)
        except Exception as e:
            log(f"  {d} taiex 失敗 {str(e)[:40]}")
        time.sleep(0.8 + random.uniform(0, 0.4))
        try:
            txf = mm.fetch_txf(d)
        except Exception as e:
            log(f"  {d} txf 失敗 {str(e)[:40]}")
        if taiex or txf:
            conn.execute(
                "UPDATE market_margin_daily SET taiex=COALESCE(?,taiex), txf=COALESCE(?,txf) WHERE date=?",
                (taiex, txf, d.isoformat()))
            conn.commit()
            ok += 1
        else:
            fail += 1
        if i % 25 == 0 or i == len(days) - 1:
            log(f"  進度 {i+1}/{len(days)}  成功={ok} 失敗={fail}  {d} 指數={taiex} 台指期={txf}")
        time.sleep(0.9 + random.uniform(0, 0.5))

    log(f"===== 疊圖回補結束 成功={ok} 失敗={fail} =====")
    n = conn.execute("SELECT COUNT(*) FROM market_margin_daily WHERE taiex IS NOT NULL AND txf IS NOT NULL").fetchone()[0]
    log(f"兩欄皆有值: {n} 筆")
    conn.close()


if __name__ == "__main__":
    main()
