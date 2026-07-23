"""investing.com 經濟行事曆 API（Next.js 時代的新端點）。

反推結果（2026-07-20 實測）：舊的 economic-calendar/Service/getCalendarFilteredData 已 404 汰換。
現行前端走：
    GET https://endpoints.investing.com/pd-instruments/v1/calendars/economic/events/occurrences
    參數 start_date / end_date（ISO8601 需帶 Z 或時區）、country_ids（逗號串）、
         importance=low,medium,high、domain_id=1、limit（**上限 1000**，預設 100）、cursor
    回應 {occurrences:[...], events:[...], next_page_cursor}，兩張表以 event_id join。**免認證**。
base host 來自頁面 __NEXT_DATA__ 的 runtimeConfig.api.instrumentsApi。
"""
import datetime
import json
import pathlib
import urllib.parse

API = "https://endpoints.investing.com/pd-instruments/v1/calendars/economic/events/occurrences"
PAGE_URL = "https://www.investing.com/economic-calendar/"
MAX_LIMIT = 1000
_HEADERS = {
    "Accept": "application/json",
    "Origin": "https://www.investing.com",
    "Referer": "https://www.investing.com/",
}
_COUNTRY_CACHE = pathlib.Path(__file__).resolve().parents[4] / "data" / "calendar_raw" / "econ_countries.json"

# investing 官方分區 → 本專案分區（正本在 regions.py，與假期資料共用）
from .regions import REGION_FROM_GROUP as _REGION_MAP

_IMP = {"low": 1, "medium": 2, "high": 3}


def load_country_map(refresh=False):
    """回傳 {country_id(str): (國家名, 本專案分區)}。取自經濟行事曆頁的 __NEXT_DATA__，快取到檔案。"""
    if not refresh and _COUNTRY_CACHE.exists():
        raw = json.loads(_COUNTRY_CACHE.read_text(encoding="utf-8"))
        return {k: (v[0], _REGION_MAP.get(v[1], "其他")) for k, v in raw.items()}
    from bs4 import BeautifulSoup
    from .fetch import fetch
    html = fetch(PAGE_URL)
    data = json.loads(BeautifulSoup(html, "lxml").find("script", id="__NEXT_DATA__").string)
    groups = data["props"]["pageProps"]["state"]["countryStore"]["eventAndHolidayCountries"]
    raw = {str(c["id"]): (c["name"], g["name"]) for g in groups for c in g["countries"]}
    _COUNTRY_CACHE.parent.mkdir(parents=True, exist_ok=True)
    _COUNTRY_CACHE.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return {k: (v[0], _REGION_MAP.get(v[1], "其他")) for k, v in raw.items()}


def _fmt(val, unit, precision):
    """把數值格式化成接近 investing 顯示（含單位）。None → 空字串。"""
    if val is None:
        return ""
    try:
        p = precision if isinstance(precision, int) and 0 <= precision <= 6 else 2
        s = f"{float(val):,.{p}f}"
    except (TypeError, ValueError):
        s = str(val)
    return f"{s}{unit or ''}"


def fetch_econ_range(start_date, end_date, country_ids, limit=MAX_LIMIT, pace=True, max_pages=40):
    """抓 start_date~end_date（YYYY-MM-DD）的經濟事件。游標翻頁至抓完。回傳 (occurrences, events_map, pages)。"""
    from .fetch import fetch, stage_sleep
    occ_all, ev_map, cursor, pages = [], {}, None, 0
    while True:
        params = {
            "start_date": f"{start_date}T00:00:00Z",
            "end_date": f"{end_date}T23:59:59Z",
            "country_ids": ",".join(country_ids),
            "importance": "low,medium,high",
            "domain_id": "1",
            "limit": str(limit),
        }
        if cursor:
            params["cursor"] = cursor
        qs = urllib.parse.urlencode(params)
        d = json.loads(fetch(f"{API}?{qs}", headers=_HEADERS, timeout=90))
        occ = d.get("occurrences", []) or []
        for e in d.get("events", []) or []:
            ev_map[e["event_id"]] = e
        occ_all += occ
        pages += 1
        cursor = d.get("next_page_cursor")
        if not cursor or not occ or pages >= max_pages:
            break
        if pace:
            stage_sleep()
    return occ_all, ev_map, pages


def to_rows(occurrences, ev_map, cmap):
    """把 API 結構轉成 events 表的列；時間 UTC → 台灣時間 GMT+8（日期會跟著位移）。"""
    rows = []
    for o in occurrences:
        e = ev_map.get(o.get("event_id"))
        if not e:
            continue
        ts = o.get("occurrence_time")
        if not ts:
            continue
        try:
            dt_utc = datetime.datetime.strptime(ts.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z")
        except ValueError:
            continue
        local = dt_utc + datetime.timedelta(hours=8)  # GMT+8
        cname, region = cmap.get(str(e.get("country_id")), ("其他", "其他"))
        name = e.get("long_name") or e.get("short_name") or e.get("event_meta_title") or "?"
        suffix = e.get("event_cycle_suffix")
        if suffix and suffix not in name:
            name = f"{name} ({suffix})"
        period = o.get("reference_period")
        if period:
            name = f"{name}（{period}）"
        unit, prec = o.get("unit"), o.get("precision")
        rows.append({
            "date": local.strftime("%Y-%m-%d"),
            "time": local.strftime("%H:%M"),
            "country": cname,
            "region": region,
            "importance": _IMP.get(str(e.get("importance", "")).lower(), 1),
            "name": name,
            "actual": _fmt(o.get("actual"), unit, prec),
            "forecast": _fmt(o.get("forecast"), unit, prec),
            "previous": _fmt(o.get("previous"), unit, prec),
            "source": "investing",
        })
    return rows
