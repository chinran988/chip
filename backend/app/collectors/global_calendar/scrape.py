"""分階段爬取 CLI。

用法：
    uv run python scrape.py holidays            # live 抓假期（單頁）
    uv run python scrape.py holidays --file data/raw/holiday_calendar.html   # 用存檔解析（不打伺服器）

節流：多階段之間以 fetch.stage_sleep() 等待 60±15s（使用者指定）。
"""
import argparse
import calendar as _cal
import datetime
import json
import pathlib
import sys

# Windows 主控台預設 cp1252，印中文會炸 → 強制 UTF-8（沿用專案慣例）
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

from .db import conn, upsert_holidays, upsert_events, log, range_done, mark_range
from .holidays import parse_holidays

HOL_SVC = "https://www.investing.com/holiday-calendar/service/getCalendarFilteredData"
# 涵蓋全部國家：country[] 掃 1..249（不存在的 ID 無害）
_COUNTRIES = [("country[]", str(i)) for i in range(1, 250)]


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def fetch_hol_range(df, dt, pace_between_pages=True, max_pages=60):
    """抓 df~dt 全部假期。端點每批上限約 200 筆，需以 limit_from＋last_time_scope 翻頁至抓完。
    回傳 (rows, pages)。批次之間 60±15s 節流。"""
    from .fetch import fetch, stage_sleep
    all_rows, limit_from, last_scope, pages = [], 0, None, 0
    while True:
        payload = _COUNTRIES + [("dateFrom", df), ("dateTo", dt), ("currentTab", "custom"), ("limit_from", str(limit_from))]
        if last_scope is not None:
            payload.append(("last_time_scope", str(last_scope)))
        j = json.loads(fetch(HOL_SVC, method="POST", data=payload))
        rows = parse_holidays(j.get("data", ""))
        pages += 1
        if not rows:
            break
        all_rows += rows
        limit_from = len(all_rows)
        last_scope = j.get("last_time_scope")
        if not j.get("bind_scroll_handler"):
            break
        if rows[-1]["date"] > dt:  # 分頁已越過區間尾端
            break
        if pages >= max_pages:
            print(f"[warn] {df}~{dt} 達分頁上限 {max_pages}，可能未抓完", flush=True)
            break
        if pace_between_pages:
            stage_sleep()
    all_rows = [x for x in all_rows if df <= x["date"] <= dt]  # 去除溢出區間的列
    return all_rows, pages


def run_holidays_hist(y_from, y_to):
    """Phase 1 假期歷史爬取：逐年抓（年內自動翻頁）。每次請求間 60±15s 節流。可續傳（已完成的年份跳過）。"""
    from .fetch import stage_sleep
    c = conn()
    grand = 0
    years = list(range(y_from, y_to + 1))
    print(f"[hist] 假期歷史 {y_from}~{y_to}（{len(years)} 年）；每次請求間 60±15s；可續傳", flush=True)
    for idx, y in enumerate(years):
        df, dt = f"{y}-01-01", f"{y}-12-31"
        if range_done(c, "holidays", df, dt):
            print(f"[hist] {y} 已完成，跳過", flush=True)
            continue
        try:
            rows, pages = fetch_hol_range(df, dt)
            n = upsert_holidays(c, rows, _now())
            mark_range(c, "holidays", df, dt, n, True)
            log(c, "holidays-hist", True, n, f"{y} ({pages}p)")
            c.commit()
            grand += n
            print(f"[hist] {y} → {n} 筆（{pages} 頁）入庫；本次累計 {grand}", flush=True)
        except Exception as e:
            mark_range(c, "holidays", df, dt, 0, False)
            log(c, "holidays-hist", False, 0, f"{y}: {e}")
            c.commit()
            print(f"[hist] {y} 失敗：{e}（重跑可續傳）", flush=True)
        if idx < len(years) - 1:
            stage_sleep()
    total = c.execute("SELECT COUNT(*) n FROM holidays").fetchone()["n"]
    dr = c.execute("SELECT MIN(date) a, MAX(date) b FROM holidays").fetchone()
    print(f"[hist] 完成。DB 假期共 {total} 筆，{dr['a']}~{dr['b']}", flush=True)
    c.close()


def run_econ_hist(y_from, y_to):
    """經濟事件歷史爬取：逐月抓（月內以 limit=1000＋游標翻頁）。每次請求間 60±15s。可續傳。
    首次成功入庫後會清掉 seed 的範例事件（source='sample'）。"""
    from .fetch import stage_sleep
    from .economics import load_country_map, fetch_econ_range, to_rows
    c = conn()
    cmap = load_country_map()
    cids = list(cmap.keys())
    months = [(y, m) for y in range(y_from, y_to + 1) for m in range(1, 13)]
    print(f"[econ] 經濟事件 {y_from}~{y_to}（{len(months)} 個月，{len(cids)} 國）；"
          f"limit=1000＋游標翻頁；每次請求間 60±15s；可續傳", flush=True)
    grand, sample_cleared = 0, False
    for idx, (y, m) in enumerate(months):
        last = _cal.monthrange(y, m)[1]
        df, dt = f"{y}-{m:02d}-01", f"{y}-{m:02d}-{last}"
        if range_done(c, "events", df, dt):
            print(f"[econ] {y}-{m:02d} 已完成，跳過", flush=True)
            continue
        try:
            occ, ev, pages = fetch_econ_range(df, dt, cids)
            rows = to_rows(occ, ev, cmap)
            n = upsert_events(c, rows, _now())
            if not sample_cleared:
                d = c.execute("DELETE FROM events WHERE source='sample'").rowcount
                if d:
                    print(f"[econ] 已清除 {d} 筆範例事件（改用真實資料）", flush=True)
                sample_cleared = True
            mark_range(c, "events", df, dt, n, True)
            log(c, "econ-hist", True, n, f"{y}-{m:02d} ({pages}p)")
            c.commit()
            grand += n
            print(f"[econ] {y}-{m:02d} → {n} 筆（{pages} 頁）入庫；本次累計 {grand}", flush=True)
        except Exception as e:
            mark_range(c, "events", df, dt, 0, False)
            log(c, "econ-hist", False, 0, f"{y}-{m:02d}: {e}")
            c.commit()
            print(f"[econ] {y}-{m:02d} 失敗：{e}（重跑可續傳）", flush=True)
        if idx < len(months) - 1:
            stage_sleep()
    total = c.execute("SELECT COUNT(*) n FROM events").fetchone()["n"]
    dr = c.execute("SELECT MIN(date) a, MAX(date) b FROM events").fetchone()
    print(f"[econ] 完成。DB 事件共 {total} 筆，{dr['a']}~{dr['b']}", flush=True)
    c.close()


def run_holidays(from_file=None):
    if from_file:
        html = pathlib.Path(from_file).read_text(encoding="utf-8")
        note = f"file:{from_file}"
    else:
        from .fetch import fetch  # 延遲載入，用存檔時免依賴 curl_cffi
        html = fetch("https://www.investing.com/holiday-calendar/")
        note = "live:holiday-calendar"
    rows = parse_holidays(html)
    c = conn()
    n = upsert_holidays(c, rows, _now())
    log(c, "holidays", True, n, note)
    c.commit()
    # 摘要
    cur = c.execute("SELECT region, COUNT(*) n FROM holidays GROUP BY region ORDER BY n DESC")
    dist = {r["region"]: r["n"] for r in cur}
    total = c.execute("SELECT COUNT(*) n FROM holidays").fetchone()["n"]
    dr = c.execute("SELECT MIN(date) a, MAX(date) b FROM holidays").fetchone()
    print(f"[holidays] 解析 {len(rows)} 列 → 入庫，DB 現有 {total} 筆，日期 {dr['a']}~{dr['b']}")
    print(f"[holidays] 分區：{dist}")
    c.close()
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("holidays")
    h.add_argument("--file", default=None)
    hh = sub.add_parser("holidays-hist")
    hh.add_argument("--from", dest="y_from", type=int, required=True)
    hh.add_argument("--to", dest="y_to", type=int, required=True)
    eh = sub.add_parser("econ-hist")
    eh.add_argument("--from", dest="y_from", type=int, required=True)
    eh.add_argument("--to", dest="y_to", type=int, required=True)
    args = ap.parse_args()
    if args.cmd == "holidays":
        run_holidays(args.file)
    elif args.cmd == "holidays-hist":
        run_holidays_hist(args.y_from, args.y_to)
    elif args.cmd == "econ-hist":
        run_econ_hist(args.y_from, args.y_to)
