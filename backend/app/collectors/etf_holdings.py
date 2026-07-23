"""CHIP-ETF 每日成分股採集器（PCF 申購買回清單持股）。

對標 etfcross.com。各投信格式不一 → per-投信 parser；底層一律走 BaseCollector.upsert()。

反爬/連線注意：
- 投信站憑證鏈缺 Subject Key Identifier，Python requests 會 CERT 驗證失敗
  （curl/瀏覽器較寬鬆）→ 一律 verify=False（見 _http）。
- 6 家投信 5 家純 HTTP（元大/富邦/群益/統一/復華），僅國泰需 headless（batch 2）。
- 元大/富邦用股票代號直接查；群益/統一/復華/國泰要先解「代號→內部碼」對照（存 registry code 欄）。

資料源實勘：CHIP-ETF/reports/2026-07-20-P0-{A,B,C}-*.md、etf_pcf_routing.md
"""
from __future__ import annotations

import io
import re
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import requests
import urllib3

from app.collectors.base import BaseCollector
from app.models.etf import EtfHolding, EtfInfo

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}
_TW_CODE = re.compile(r"^\d{4,6}[A-Z]?$")  # 台股代號（相容 00400A 這種帶字母 ETF 代號）


# ── ETF 主檔 registry（14 檔，seed etf_info；batch/code 供採集器分批與內部碼查表）──────
# batch: 1a=元大/富邦台股(HTML), 1b=群益/統一台股(JSON), 2=國泰(headless),
#        foreign=國外成分股(外股, 需另處理), blocked=已知端點查無資料
ETF_REGISTRY = [
    dict(etf_id="0050", name="元大台灣50", full_name="元大台灣卓越50證券投資信託基金",
         issuer="元大", category="國內成分股ETF", is_active=False, is_domestic=True,
         pcf_url="https://www.yuantaetfs.com/#/Orders/1066",
         data_endpoint="https://www.yuantaetfs.com/product/detail/0050/ratio",
         engine="http", code=None, batch="1a"),
    dict(etf_id="0056", name="元大高股息", full_name="元大台灣高股息證券投資信託基金",
         issuer="元大", category="國內成分股ETF", is_active=False, is_domestic=True,
         pcf_url="https://www.yuantaetfs.com/#/Orders/1084",
         data_endpoint="https://www.yuantaetfs.com/product/detail/0056/ratio",
         engine="http", code=None, batch="1a"),
    dict(etf_id="006208", name="富邦台50", full_name="富邦台灣釆吉50證券投資信託基金",
         issuer="富邦", category="國內成分股ETF", is_active=False, is_domestic=True,
         pcf_url="https://websys.fsit.com.tw/FubonETF/Trade/Pcf.aspx?stkId=006208&lan=TW",
         data_endpoint="https://websys.fsit.com.tw/FubonETF/Fund/Assets.aspx?stkId=006208",
         engine="http", code=None, batch="1a"),
    dict(etf_id="0052", name="富邦科技", full_name="富邦台灣科技指數證券投資信託基金",
         issuer="富邦", category="國內成分股ETF", is_active=False, is_domestic=True,
         pcf_url="https://websys.fsit.com.tw/FubonETF/Trade/Pcf.aspx?stkId=0052&lan=TW",
         data_endpoint="https://websys.fsit.com.tw/FubonETF/Fund/Assets.aspx?stkId=0052",
         engine="http", code=None, batch="1a"),
    dict(etf_id="00919", name="群益台灣精選高息", full_name="群益台灣精選高息ETF證券投資信託基金",
         issuer="群益", category="國內成分股ETF", is_active=False, is_domestic=True,
         pcf_url="https://www.capitalfund.com.tw/etf/transaction/buyback",
         data_endpoint="https://www.capitalfund.com.tw/CFWeb/api/etf/buyback",
         engine="http", code="195", batch="1b"),
    dict(etf_id="00982A", name="主動群益台灣強棒", full_name="群益台灣精選強棒主動式ETF證券投資信託基金",
         issuer="群益", category="國內成分股ETF", is_active=True, is_domestic=True,
         pcf_url="https://www.capitalfund.com.tw/etf/transaction/buyback",
         data_endpoint="https://www.capitalfund.com.tw/CFWeb/api/etf/buyback",
         engine="http", code="399", batch="1b"),
    dict(etf_id="00992A", name="主動群益科技創新", full_name="群益台灣科技創新主動式ETF證券投資信託基金",
         issuer="群益", category="國內成分股ETF", is_active=True, is_domestic=True,
         pcf_url="https://www.capitalfund.com.tw/etf/transaction/buyback",
         data_endpoint="https://www.capitalfund.com.tw/CFWeb/api/etf/buyback",
         engine="http", code="500", batch="1b"),
    dict(etf_id="00981A", name="主動統一台股增長", full_name="統一台股增長主動式ETF證券投資信託基金",
         issuer="統一", category="國內成分股ETF", is_active=True, is_domestic=True,
         pcf_url="https://www.ezmoney.com.tw/ETF/Transaction/PCF",
         data_endpoint="https://www.ezmoney.com.tw/ETF/Transaction/GetPCF",
         engine="http", code="49YTW", batch="1b"),
    dict(etf_id="00403A", name="主動統一升級50", full_name="統一台股升級50主動式ETF證券投資信託基金",
         issuer="統一", category="國內成分股ETF", is_active=True, is_domestic=True,
         pcf_url="https://www.ezmoney.com.tw/ETF/Transaction/PCF",
         data_endpoint="https://www.ezmoney.com.tw/ETF/Transaction/GetPCF",
         engine="http", code="63YTW", batch="1b"),
    dict(etf_id="00991A", name="主動復華未來50", full_name="復華台灣未來50主動式ETF證券投資信託基金",
         issuer="復華", category="國內成分股ETF", is_active=True, is_domestic=True,
         pcf_url="https://www.fhtrust.com.tw/ETF/trade_list",
         # 注意：`/api/ETFPcf` 對 00991A 一律回空陣列（且 schema 無權重）；
         # 可用的是基金資產頁背後的 `/api/assets`。
         data_endpoint="https://www.fhtrust.com.tw/api/assets",
         engine="http", code="ETF23", batch="1b"),
    dict(etf_id="00988A", name="主動統一全球創新", full_name="統一全球創新主動式ETF證券投資信託基金",
         issuer="統一", category="國外成分股ETF(含連結式ETF)", is_active=True, is_domestic=False,
         pcf_url="https://www.ezmoney.com.tw/ETF/Transaction/PCF",
         data_endpoint="https://www.ezmoney.com.tw/ETF/Transaction/GetPCF",
         engine="http", code="61YTW", batch="foreign"),
    dict(etf_id="00990A", name="主動元大AI新經濟", full_name="元大全球AI新經濟主動式ETF證券投資信託基金",
         issuer="元大", category="國外成分股ETF(含連結式ETF)", is_active=True, is_domestic=False,
         pcf_url="https://www.yuantaetfs.com/tradeInfo/pcf/00990A",
         data_endpoint="https://www.yuantaetfs.com/product/detail/00990A/ratio",
         engine="http", code=None, batch="foreign"),
    # 國泰：原判定需 headless，實測其 Angular 前端呼叫的 cwapi 可純 HTTP 直取
    # （GetETFDetailStockList），且 SearchDate 嚴格對應——**唯一可回溯歷史的投信**。
    dict(etf_id="00878", name="國泰永續高股息", full_name="國泰台灣ESG永續高股息ETF證券投資信託基金",
         issuer="國泰", category="國內成分股ETF", is_active=False, is_domestic=True,
         pcf_url="https://www.cathaysite.com.tw/ETF/purchase?code=CN",
         data_endpoint="https://cwapi.cathaysite.com.tw/api/ETF/GetETFDetailStockList",
         engine="http", code="CN", batch="2"),
    dict(etf_id="00400A", name="主動國泰動能高息", full_name="國泰台股動能高息主動式ETF證券投資信託基金",
         issuer="國泰", category="國內成分股ETF", is_active=True, is_domestic=True,
         pcf_url="https://www.cathaysite.com.tw/ETF/purchase",
         data_endpoint="https://cwapi.cathaysite.com.tw/api/ETF/GetETFDetailStockList",
         engine="http", code="EA", batch="2"),
]
_BY_ID = {e["etf_id"]: e for e in ETF_REGISTRY}


# ── 小工具 ─────────────────────────────────────────────────────────────────
# 注意：必須吃得下「前導小數點」格式（元大權重會出現 .19 = 0.19%）。
# 舊版正則 -?\d+(?:\.\d+)? 會把 ".19" 讀成 19.0，小權重放大 100 倍。
_NUM = re.compile(r"-?(?:\d+\.\d+|\.\d+|\d+)")


def _to_int(x) -> int | None:
    m = _NUM.search(str(x).replace(",", "").strip())
    return int(float(m.group())) if m else None


def _to_float(x) -> float | None:
    m = _NUM.search(str(x).replace(",", "").replace("%", "").strip())
    return float(m.group()) if m else None


def _strip_tags(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def _split_js(s: str) -> list[str]:
    """依頂層逗號切 JS 參數/物件欄位，尊重字串引號與括號巢狀。"""
    out, buf, depth, quote, esc = [], [], 0, None, False
    for ch in s:
        if esc:
            buf.append(ch); esc = False; continue
        if quote:
            buf.append(ch)
            if ch == "\\":
                esc = True
            elif ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch; buf.append(ch); continue
        if ch in "[{(":
            depth += 1
        elif ch in "]})":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(buf).strip()); buf = []; continue
        buf.append(ch)
    if buf:
        out.append("".join(buf).strip())
    return out


def _mk_date(y, m, d) -> date:
    return date(int(y), int(m), int(d))


_TW_TZ = timezone(timedelta(hours=8))  # 台灣 GMT+8


def _ms_date(val) -> date | None:
    """統一投信的日期欄位 → 台灣當地日期。

    同一支 API 實測會回兩種序列化格式（會隨請求飄移，只吃一種會間歇性掉資料）：
      1. MS-JSON  `/Date(1784476800000)/`（UTC 毫秒）
      2. ISO      `2026-07-20T00:00:00`
    """
    s = str(val)
    m = re.search(r"/Date\((-?\d+)\)/", s)
    if m:
        return (datetime(1970, 1, 1, tzinfo=timezone.utc)
                + timedelta(milliseconds=int(m.group(1)))).astimezone(_TW_TZ).date()
    m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
    return _mk_date(*m.groups()) if m else None


def _roc_today() -> str:
    """統一投信 API 要民國年格式 date 參數，如 115/07/20。"""
    t = datetime.now(_TW_TZ).date()
    return f"{t.year - 1911}/{t.month:02d}/{t.day:02d}"


# ── per-投信 parser：回 (data_date, rows[])，rows 是可直接 upsert 的 dict ────────
def _parse_yuanta(html: str, etf_id: str, domestic_only: bool = True) -> tuple[date | None, list[dict]]:
    """元大：Nuxt 2 SSR。

    可見 HTML 的 div-grid 只渲染「前 5 大」預覽，完整持股在 window.__NUXT__ payload 的
    FundWeights.StockWeights[]。payload 是壓縮過的 function(參數...){...}(引數...) 形式，
    code/name 是變數引用，需用「參數↔引數」位置對應還原（qty/weights 則是明碼）。
    """
    # 資料日期：標籤「基金權重-股票 交易日期:」與日期之間隔著 HTML tag，先去標籤再比對
    txt = _strip_tags(html)
    d = None
    m = (re.search(r"基金權重-股票\s*交易日期[:：]?\s*(\d{4})/(\d{1,2})/(\d{1,2})", txt)
         or re.search(r"交易日期[:：]?\s*(\d{4})/(\d{1,2})/(\d{1,2})", txt))
    if m:
        d = _mk_date(*m.groups())

    start = html.find("window.__NUXT__=")
    if start < 0:
        return d, []
    seg = html[start:html.index("</script>", start)]
    try:
        params = [p.strip() for p in re.search(r"\(function\(([^)]*)\)", seg).group(1).split(",")]
        args = _split_js(seg[seg.rindex("}(") + 2: seg.rindex("))") + 1])
    except (AttributeError, ValueError):
        return d, []
    varmap = dict(zip(params, args)) if len(params) == len(args) else {}

    def rv(tok: str) -> str:
        tok = tok.strip()
        if tok in varmap:
            tok = varmap[tok].strip()
        if len(tok) >= 2 and tok[0] in "\"'" and tok[-1] == tok[0]:
            return tok[1:-1]
        return tok

    mm = re.search(r"StockWeights:\[(.*?)\](?=,|\})", seg, re.S)
    if not mm:
        return d, []
    rows = []
    for ent in re.findall(r"\{([^{}]*)\}", mm.group(1)):
        f = {}
        for kv in _split_js(ent):
            if ":" in kv:
                k, v = kv.split(":", 1)
                f[k.strip()] = v.strip()
        code = rv(f.get("code", ""))
        if not code or (domestic_only and not _TW_CODE.match(code)):
            continue
        rows.append(dict(etf_id=etf_id, stock_id=code, stock_name=rv(f.get("name", "")),
                         shares=_to_int(rv(f.get("qty", ""))),
                         weight=_to_float(rv(f.get("weights", ""))), market_value=None))
    return d, rows


def _parse_fubon(html: str, etf_id: str) -> tuple[date | None, list[dict]]:
    """富邦：ASP.NET SSR，read_html 抓到的持股表首列是表頭
    [股票代碼, 股票名稱, 股數, 金額, 權重(%)]。
    """
    d = None
    m = re.search(r"資料日期[:：]\s*(\d{4})[/.\-](\d{1,2})[/.\-](\d{1,2})", html)
    if m:
        d = _mk_date(*m.groups())
    # header=None → 欄位一律位置化，避免 pandas 表頭推斷不穩定（曾導致回 0 列）；
    # 取「台股代號列最多」的那張表當持股表，自動跳過期貨/現金/其他資產列。
    best: list = []
    for t in pd.read_html(io.StringIO(html), header=None):
        if t.shape[1] < 5:
            continue
        cand = [r for _, r in t.iterrows() if _TW_CODE.match(str(r.iloc[0]).strip())]
        if len(cand) > len(best):
            best = cand
    rows = [dict(etf_id=etf_id, stock_id=str(r.iloc[0]).strip(), stock_name=str(r.iloc[1]).strip(),
                 shares=_to_int(r.iloc[2]), market_value=_to_int(r.iloc[3]), weight=_to_float(r.iloc[4]))
            for r in best]
    return d, rows


def _parse_capital(payload: dict, etf_id: str, domestic_only: bool = True) -> tuple[date | None, list[dict]]:
    """群益：JSON API。個股在 data.stocks[]（stocNo/stocName/share/weight）。

    日期取 data.pcf.date2＝資料基準日；date1 是隔一營業日的生效日，
    stocks[].date1 同樣是生效日，用錯會讓群益的快照比其他投信超前一天。
    """
    data = payload.get("data") or {}
    d = None
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", str((data.get("pcf") or {}).get("date2") or ""))
    if m:
        d = _mk_date(*m.groups())
    rows = []
    for s in data.get("stocks") or []:
        code = str(s.get("stocNo") or "").strip()
        if not code or (domestic_only and not _TW_CODE.match(code)):
            continue
        rows.append(dict(etf_id=etf_id, stock_id=code, stock_name=str(s.get("stocName") or "").strip(),
                         shares=_to_int(s.get("share")), weight=_to_float(s.get("weight")),
                         market_value=None))
    return d, rows


def _parse_uni(payload: dict, etf_id: str, domestic_only: bool = True) -> tuple[date | None, list[dict]]:
    """統一：JSON API。個股藏兩層深——asset[AssetCode=='ST'].Details[]。

    頂層 pcf[] 只是基金層級彙總（淨值/受益權單位），沒有個股。
    日期取 Details[].TranDate＝資料基準日（PostDate 是發布日，會超前一天）。
    """
    d, rows = None, []
    for grp in payload.get("asset") or []:
        if grp.get("AssetCode") != "ST":
            continue
        for it in grp.get("Details") or []:
            if d is None:
                d = _ms_date(it.get("TranDate"))
            code = str(it.get("DetailCode") or "").strip()
            if not code or (domestic_only and not _TW_CODE.match(code)):
                continue
            rows.append(dict(etf_id=etf_id, stock_id=code,
                             stock_name=str(it.get("DetailName") or "").strip(),
                             shares=_to_int(it.get("Share")), weight=_to_float(it.get("NavRate")),
                             market_value=_to_int(it.get("Amount"))))
    return d, rows


def _parse_cathay(payload: dict, etf_id: str, search_date: date,
                  domestic_only: bool = True) -> tuple[date | None, list[dict]]:
    """國泰：cwapi JSON（result[] 的 stockCode/stockName/volumn/weights）。

    回應本身不帶日期，但實測 SearchDate 參數「嚴格對應」——週末/未公告日回 0 筆，
    不會回退成舊資料，因此可安心把請求日期當基準日。
    """
    rows = []
    for it in payload.get("result") or []:
        code = str(it.get("stockCode") or "").strip()
        if not code or (domestic_only and not _TW_CODE.match(code)):
            continue
        rows.append(dict(etf_id=etf_id, stock_id=code,
                         stock_name=str(it.get("stockName") or "").strip(),
                         shares=_to_int(it.get("volumn")), weight=_to_float(it.get("weights")),
                         market_value=None))
    return (search_date if rows else None), rows


def _parse_fuhua(payload: dict, etf_id: str, domestic_only: bool = True) -> tuple[date | None, list[dict]]:
    """復華：`/api/assets` JSON（**不是**先前查到會回空的 `/api/ETFPcf`）。

    持股在 result[0].detail[]（ftype=='股票'），欄位 stockid/stockname/qshare/mvalue/prate_addaccint。
    日期直接取回應自帶的 result[0].dDate（非交易日回 None，不會回退舊資料）——
    比信任請求日期更安全。
    """
    res = ((payload.get("result") or [None])[0]) or {}
    d = None
    m = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", str(res.get("dDate") or ""))
    if m:
        d = _mk_date(*m.groups())
    rows = []
    for it in res.get("detail") or []:
        if str(it.get("ftype") or "").strip() != "股票":
            continue
        code = str(it.get("stockid") or "").strip()
        if not code or (domestic_only and not _TW_CODE.match(code)):
            continue
        rows.append(dict(etf_id=etf_id, stock_id=code,
                         stock_name=str(it.get("stockname") or "").strip(),
                         shares=_to_int(it.get("qshare")),
                         weight=_to_float(it.get("prate_addaccint")),
                         market_value=_to_int(it.get("mvalue"))))
    return d, rows


class EtfHoldingCollector(BaseCollector):
    name = "etf_holdings"

    # 多檔 ETF、多來源 → 不走 BaseCollector 單一 fetch/parse/save 模板，
    # 自訂 collect_one/collect_all 入口（比照 tpex_chip.py），底層仍用 self.upsert()。
    def fetch(self, target_date):  # pragma: no cover - 模板方法未使用
        return {}

    def parse(self, raw, target_date):  # pragma: no cover
        return []

    def save(self, rows: list[dict]) -> int:
        return self.upsert(EtfHolding, rows, ["date", "etf_id", "stock_id"])

    def _http(self, url: str) -> str:
        resp = requests.get(url, headers=_UA, timeout=40, verify=False)
        resp.raise_for_status()
        return resp.text

    def _get_json(self, url: str, params: dict, referer: str = "") -> dict:
        headers = {**_UA, "Accept": "application/json"}
        if referer:
            headers["Referer"] = referer
        resp = requests.get(url, headers=headers, params=params, timeout=40, verify=False)
        resp.raise_for_status()
        return resp.json()

    def _post_json(self, url: str, body: dict, bootstrap: str | None = None) -> dict:
        """POST JSON。bootstrap 供統一投信使用——需先 GET 落地頁換 session cookie
        （__nxquid），否則直接 POST 會被擋 307。requests.Session 自動帶 cookie。"""
        s = requests.Session()
        s.verify = False
        s.headers.update({**_UA, "Content-Type": "application/json"})
        if bootstrap:
            s.get(bootstrap, timeout=40)
        resp = s.post(url, json=body, timeout=40)
        resp.raise_for_status()
        return resp.json()

    def seed_info(self) -> int:
        """把 registry 寫進 etf_info 主檔（upsert）。"""
        rows = [{k: e[k] for k in ("etf_id", "name", "full_name", "issuer", "category",
                                   "is_active", "is_domestic", "pcf_url", "data_endpoint", "engine")}
                for e in ETF_REGISTRY]
        n = self.upsert(EtfInfo, rows, ["etf_id"])
        self.db.commit()
        return n

    def collect_one(self, etf_id: str) -> int:
        info = _BY_ID.get(etf_id)
        if info is None:
            raise ValueError(f"unknown etf_id {etf_id}")
        issuer, dom = info["issuer"], info["is_domestic"]
        if issuer == "元大":
            d, rows = _parse_yuanta(self._http(info["data_endpoint"]), etf_id, domestic_only=dom)
        elif issuer == "富邦":
            d, rows = _parse_fubon(self._http(info["data_endpoint"]), etf_id)
        elif issuer == "群益":
            payload = self._post_json(info["data_endpoint"], {"fundId": info["code"], "date": None})
            d, rows = _parse_capital(payload, etf_id, domestic_only=dom)
        elif issuer == "統一":
            payload = self._post_json(info["data_endpoint"],
                                      {"fundCode": info["code"], "date": _roc_today(),
                                       "specificDate": False},
                                      bootstrap=info["pcf_url"])
            d, rows = _parse_uni(payload, etf_id, domestic_only=dom)
        elif issuer == "國泰":
            sd = datetime.now(_TW_TZ).date()
            payload = self._get_json(info["data_endpoint"],
                                     {"FundCode": info["code"], "SearchDate": sd.isoformat(),
                                      "status": 1},
                                     referer="https://www.cathaysite.com.tw/")
            d, rows = _parse_cathay(payload, etf_id, sd, domestic_only=dom)
        elif issuer == "復華":
            payload = self._get_json(info["data_endpoint"],
                                     {"fundID": info["code"],
                                      "qDate": datetime.now(_TW_TZ).strftime("%Y/%m/%d")},
                                     referer="https://www.fhtrust.com.tw/")
            d, rows = _parse_fuhua(payload, etf_id, domestic_only=dom)
        else:
            raise NotImplementedError(f"parser for {issuer} not implemented yet")
        if d is None:
            self.log.warning("etf %s: 無法解析資料日期，跳過（避免存錯日期）", etf_id)
            return 0
        if not rows:
            self.log.warning("etf %s: 0 holdings parsed", etf_id)
            return 0
        for r in rows:
            r["date"] = d
        n = self.save(rows)
        self.db.commit()
        self.log.info("etf %s: saved %d holdings @ %s", etf_id, n, d)
        return n

    def collect_all(self, batch: str | None = None) -> dict:
        """採集指定 batch；batch=None ＝每日排程用的預設集合
        （所有 engine=http 且非 blocked 的 ETF，含國外成分股那兩檔）。
        回 {etf_id: 筆數 | 'error: ...'}。"""
        results = {}
        for e in ETF_REGISTRY:
            if batch is not None and e["batch"] != batch:
                continue
            if batch is None and (e["engine"] != "http" or e["batch"] == "blocked"):
                continue
            try:
                results[e["etf_id"]] = self.collect_one(e["etf_id"])
            except NotImplementedError as ex:
                results[e["etf_id"]] = f"skip: {ex}"
            except Exception as ex:  # noqa: BLE001
                self.log.error("etf %s collect failed: %s", e["etf_id"], ex)
                results[e["etf_id"]] = f"error: {ex}"
        return results
