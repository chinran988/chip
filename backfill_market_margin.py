"""回補整體融資維持率歷史（2020-06-01 → 今日）。
逐平日打 TWSE，有資料才存（假日自動跳過）；可續跑（跳過已存日）；節流防限流。
用法：python backfill_market_margin.py [START] [END]   預設 2020-06-01 → 今天
"""
import sys, os, time, sqlite3, datetime, random

BACKEND = r"C:\Users\Inspiration\Documents\Project Quant\CHIP\backend"
DB      = r"C:\Users\Inspiration\Documents\Project Quant\CHIP\data\chip.db"
LOG     = os.path.join(os.environ.get("TEMP", r"C:\Users\INSPIR~1\AppData\Local\Temp"), "market_margin_backfill.log")
sys.path.insert(0, BACKEND); os.chdir(BACKEND)
os.environ.setdefault("PYTHONUTF8", "1")
from app.collectors import market_margin as mm


def log(msg):
    line = f"[{datetime.datetime.now():%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def main():
    start = datetime.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else datetime.date(2020, 6, 1)
    end   = datetime.date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else datetime.date.today()

    conn = sqlite3.connect(DB)
    mm.ensure_table(conn)
    done = {r[0] for r in conn.execute("SELECT date FROM market_margin_daily").fetchall()}

    days = []
    d = start
    while d <= end:
        if d.weekday() < 5 and d.isoformat() not in done:   # 平日且未存
            days.append(d)
        d += datetime.timedelta(days=1)
    log(f"===== 回補開始 {start}~{end}，待處理 {len(days)} 個平日（已存 {len(done)}）=====")

    ok = holiday = fail = 0
    for i, day in enumerate(days):
        rec = None
        for attempt in range(3):
            try:
                rec = mm.compute_day(day)
                break
            except Exception as e:
                if attempt < 2:
                    time.sleep(3 + attempt * 3)   # 限流退避
                else:
                    fail += 1
                    log(f"  {day} 失敗: {str(e)[:60]}")
        if rec:
            mm.store_day(conn, rec)
            ok += 1
        elif rec is None and fail == 0:
            holiday += 1   # 非交易日
        if i % 20 == 0 or i == len(days) - 1:
            last = rec["maintenance_ratio"] if rec else "—"
            log(f"  進度 {i+1}/{len(days)}  存={ok} 假日={holiday} 失敗={fail}  {day} 維持率={last}")
        time.sleep(1.2 + random.uniform(0, 0.6))   # 節流

    log(f"===== 回補結束 存={ok} 假日={holiday} 失敗={fail} =====")
    total = conn.execute("SELECT COUNT(*) FROM market_margin_daily").fetchone()[0]
    log(f"market_margin_daily 總筆數: {total}")
    conn.close()


if __name__ == "__main__":
    main()
