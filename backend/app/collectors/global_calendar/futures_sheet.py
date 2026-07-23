"""期貨交易所假期（來源：使用者維護的 Google Sheet，含台灣時間早收）。

補 investing 假期資料的缺口：investing 只收「證券」交易所，完全沒有 CME/CBOT/COMEX 等期貨所，
也不提供「提早收盤的確切時間」。此 Sheet 為使用者手動維護、公開 CSV 匯出可直抓。

★目前 Sheet 只有「美國期貨組 CME/CBOT/COMEX」有實際資料；
  EUREX / JPX / HKEX / SGX / 上海 / 深圳 段目前僅有官方行事曆連結（未整理）→ 本收集器自動跳過。
  來源標記 source='sheet'，與 investing 資料共存於 holidays 表（同一市場多來源）。

解析策略：**忠實保存**，不臆測。放假日期取自 Sheet 的「放假日期」欄；早收時間保留 Sheet 原字串
（含 夏令/冬令 標註），不做時區再換算。若 Sheet 有內部矛盾（如放假日與早收日不同），原樣入庫並回報，不擅自「修正」。
"""
import csv
import datetime
import io
import re

SHEET_CSV = ("https://docs.google.com/spreadsheets/d/"
             "1J9HTuIzlVHf_q8mFPvTYzBzo3QmPzmky9HvfKvlpngc/export?format=csv&gid=0")
GROUP_EXCHANGES = ["CME", "CBOT", "COMEX"]   # 目前 Sheet 唯一有資料的一組（美國期貨）
COUNTRY, REGION = "United States", "美洲"

# 早收時間格式：「... (五) 2115 (夏令)」→ 抓季節標註前的 3~4 位時鐘數字（避開年份 2026/…）
_TIME_BEFORE_SEASON = re.compile(r"(\d{3,4})\s*\((?:夏令|冬令)\)")
_DATE_RE = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})")


def _iso(cell):
    m = _DATE_RE.match(cell.strip())
    if not m:
        return None
    y, mo, d = map(int, m.groups())
    try:
        return datetime.date(y, mo, d).isoformat()
    except ValueError:
        return None


def _is_early(tw_close):
    """台灣早收欄含具體時鐘時間 = 早收；『正常時間』或空 = 非早收（視為當日休市）。"""
    if not tw_close or "正常時間" in tw_close:
        return False
    return bool(_TIME_BEFORE_SEASON.search(tw_close))


def _clean(s):
    return re.sub(r"\s+", " ", s).strip() if s else None


def parse_futures_sheet(csv_text):
    """回傳 (records, anomalies)。records=可入庫的 holiday dict；anomalies=資料品質觀察（回報用）。"""
    rows = list(csv.reader(io.StringIO(csv_text)))
    groups, anomalies = [], []
    cur = None
    for r in rows[1:]:
        r = (r + [""] * 12)[:12]
        ex, prod, _tz, hol, dt = (x.strip() for x in r[:5])
        tw_open, tw_close, note0 = r[9].strip(), r[10].strip(), r[11].strip()
        if prod.startswith("http"):   # 進入 placeholder 段（EUREX 等只有連結）→ 結束
            break
        if hol:                       # 新假期起始列
            iso = _iso(dt)
            if dt and not iso:
                anomalies.append(f"假期「{hol}」放假日期無法解析：{dt!r}")
            cur = {"name": hol, "raw_date": dt, "date": iso, "variants": [], "open": tw_open, "note": note0}
            groups.append(cur)
        if cur and tw_close:          # 有台灣時間資訊的列（含商品拆分續列）
            cur["variants"].append({"product": prod, "tw_close": tw_close})
            if tw_open and not cur["open"]:
                cur["open"] = tw_open

    records = []
    for g in groups:
        if not g["date"]:
            continue
        early = [v for v in g["variants"] if _is_early(v["tw_close"])]
        if early:
            typ = "早收"
            if len(early) == 1:
                close_time = _clean(early[0]["tw_close"])
            else:  # 商品拆分：指數/金屬能源/外匯 時間不同
                close_time = " / ".join(f"{v['product']}：{_clean(v['tw_close'])}" for v in early)
            # 資料品質檢查：早收日期 vs 放假日期是否一致
            edates = {m.group(0) for v in early for m in [_DATE_RE.search(v["tw_close"])] if m}
            hol_md = g["raw_date"].split("(")[0].strip()
            for ed in edates:
                if hol_md and ed and ed.replace("-", "/") not in g["raw_date"] and hol_md not in ed:
                    anomalies.append(f"「{g['name']}」放假日={g['raw_date']} 但早收時間落在 {ed}（原樣入庫，請核對 Sheet）")
                    break
        else:
            typ, close_time = "休市", None
        for ex in GROUP_EXCHANGES:
            records.append({
                "date": g["date"], "country": COUNTRY, "exchange": ex, "region": REGION,
                "name": g["name"], "type": typ,
                "close_time": close_time, "open_time": _clean(g["open"]),
                "note": _clean(g["note"]), "source": "sheet",
            })
    return records, anomalies


def fetch_csv():
    from .fetch import fetch
    return fetch(SHEET_CSV)


def collect(csv_text=None):
    from .db import conn, upsert_holidays, log
    txt = csv_text if csv_text is not None else fetch_csv()
    records, anomalies = parse_futures_sheet(txt)
    c = conn()
    n = upsert_holidays(c, records, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    log(c, "futures-sheet", True, n, f"{'/'.join(GROUP_EXCHANGES)}; anomalies={len(anomalies)}")
    c.commit()
    c.close()
    return {
        "records": n,
        "exchanges": GROUP_EXCHANGES,
        "holidays": sorted({r["date"] + " " + r["name"] for r in records}),
        "anomalies": anomalies,
    }
