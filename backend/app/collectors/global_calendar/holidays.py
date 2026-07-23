"""investing.com 假期行事曆解析。

表格 table#holidayCalendarData，欄位：日期 | 國家 | 交易所 | 假日名。
同一天多筆時只有第一列有日期字串，需往下補（forward-fill）。
"""
import re
from datetime import datetime

from bs4 import BeautifulSoup

from .regions import region_of

# 早收關鍵字（investing 假期表以完全休市為主，早收偶爾以名稱標示）
_EARLY = re.compile(r"early close|half[- ]day|partial|shorten|abbreviated", re.I)


def _to_iso(txt):
    """'Jul 20, 2026' -> '2026-07-20'。解析失敗回 None。"""
    try:
        return datetime.strptime(txt.strip(), "%b %d, %Y").strftime("%Y-%m-%d")
    except ValueError:
        return None


def parse_holidays(html):
    soup = BeautifulSoup(html, "lxml")
    # 整頁 → table#holidayCalendarData；service 端點 → 直接是 <tr> 片段
    tbl = soup.find("table", id="holidayCalendarData")
    scope = tbl if tbl is not None else soup
    rows, cur_date = [], None
    for tr in scope.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 4:  # 表頭(th)或分隔列
            continue
        date_txt = tds[0].get_text(strip=True)
        country = tds[1].get_text(strip=True)
        exchange = tds[2].get_text(strip=True)
        name = tds[3].get_text(" ", strip=True)
        if date_txt:
            iso = _to_iso(date_txt)
            if iso:
                cur_date = iso
        if not (country or exchange) or not name or cur_date is None:
            continue
        rows.append({
            "date": cur_date,
            "country": country,
            "exchange": exchange,
            "region": region_of(country),
            "name": name,
            "type": "早收" if _EARLY.search(name) else "休市",
        })
    return rows
