"""國家 → 地區分組（繁中）。前端「分區摺疊」用。

正本＝investing 官方分組（107 國，來自經濟行事曆頁 __NEXT_DATA__ 的 countryStore，
快取於 data/raw/econ_countries.json）。實測可完整覆蓋假期表的 97 國。
手寫表僅在快取檔缺失時當後備（會漏，例如 Türkiye 新拼法、Bulgaria）。
"""
import json
import pathlib

# investing 官方分組 → 本專案分區
REGION_FROM_GROUP = {
    "Europe": "歐洲",
    "Americas": "美洲",
    "Asia/Pacific": "亞太",
    "Asia-Pacific": "亞太",
    "Africa": "中東非",
    "Middle East": "中東非",
}

REGION_ORDER = ["亞太", "歐洲", "美洲", "中東非", "其他"]

_CACHE = pathlib.Path(__file__).resolve().parents[4] / "data" / "calendar_raw" / "econ_countries.json"

# 後備（快取缺失時用；不完整）
_FALLBACK = {}
for _c in ("Japan China Hong-Kong Taiwan Singapore South-Korea India Thailand Malaysia Indonesia "
           "Philippines Vietnam Australia New-Zealand Pakistan Sri-Lanka Bangladesh Mongolia").split():
    _FALLBACK[_c.replace("-", " ")] = "亞太"
for _c in ("United-Kingdom Germany France Italy Spain Netherlands Switzerland Sweden Norway Denmark "
           "Finland Poland Austria Belgium Ireland Portugal Greece Russia Türkiye Turkey Czech-Republic "
           "Hungary Romania Ukraine Iceland Luxembourg Cyprus Malta Slovakia Slovenia Croatia Estonia "
           "Latvia Lithuania Serbia Bulgaria Montenegro Bosnia-Herzegovina").split():
    _FALLBACK[_c.replace("-", " ")] = "歐洲"
for _c in ("United-States Canada Brazil Mexico Argentina Chile Colombia Peru Venezuela Costa-Rica "
           "Jamaica Bermuda Ecuador Uruguay Cayman-Islands").split():
    _FALLBACK[_c.replace("-", " ")] = "美洲"
for _c in ("Israel Saudi-Arabia United-Arab-Emirates Qatar Egypt South-Africa Nigeria Kenya Botswana "
           "Tunisia Morocco Kuwait Bahrain Oman Jordan Mauritius Ghana Lebanon Namibia Zimbabwe "
           "Tanzania Rwanda Uganda Malawi Zambia Iraq Palestinian-Territory").split():
    _FALLBACK[_c.replace("-", " ")] = "中東非"


def _load():
    m = dict(_FALLBACK)
    try:
        raw = json.loads(_CACHE.read_text(encoding="utf-8"))
        for name, group in raw.values():           # {id: [name, group]}
            m[name] = REGION_FROM_GROUP.get(group, "其他")
    except Exception:
        pass
    return m


_MAP = _load()


def region_of(country):
    if not country:
        return "其他"
    return _MAP.get(country.strip(), "其他")


def reload_map():
    """快取更新後重新載入。"""
    global _MAP
    _MAP = _load()
    return len(_MAP)
