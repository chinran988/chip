"""個股每日行情 — TWSE MI_INDEX (type=ALLBUT0999，全部不含權證/牛熊證)。

新增動機（CHIP-ETF 模組）：
  - 交集表「涉及總資金」＝ Σ(ETF 持股股數 × 當日收盤價)
  - 異動歷史成本估算三口徑：均價／最低／最高

為什麼不用「ETF 自報市值 ÷ 股數」反推價格：實測覆蓋率僅 ~68%（只有富邦/統一/復華
有給市值），且各投信基準日不一，同一檔股票跨來源反推價差可達 9.9%（聯電 130 vs 144）。
故改接官方逐檔行情。

※ 本來源只涵蓋上市(TWSE)。上櫃(OTC)個股需另接 TPEx，尚未實作（見 CHIP-ETF/TODO.md）。
"""
from __future__ import annotations

import json as _json
import re
import ssl
import urllib.request
from datetime import date

from app.collectors.base import BaseCollector
from app.core.config import settings
from app.models.raw import RawStockPrice

_TPEX_BASE = "https://www.tpex.org.tw/openapi/v1"

_STOCK_RE = re.compile(r"^\d{4,6}[A-Z]?$")  # 相容 00400A 這類帶字母代號


def _num(val) -> float | None:
    s = str(val).replace(",", "").strip()
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


class StockPriceCollector(BaseCollector):
    name = "twse_stock_price"

    def fetch(self, target_date: date) -> dict:
        resp = self.get(
            f"{settings.TWSE_BASE_URL}/exchangeReport/MI_INDEX",
            params={"response": "json", "date": target_date.strftime("%Y%m%d"),
                    "type": "ALLBUT0999"},
            referer=settings.TWSE_BASE_URL,
        )
        return resp.json()

    def parse(self, raw: dict, target_date: date) -> list[dict]:
        if raw.get("stat") != "OK":
            self.log.warning("MI_INDEX stat=%s for %s", raw.get("stat"), target_date)
            return []
        rows: list[dict] = []
        # 逐檔行情是 tables 裡「含收盤價欄位且資料筆數最多」的那張（實測為 tables[8]，
        # 但索引會隨 TWSE 改版飄移，故用欄位特徵挑，不寫死索引）。
        for t in raw.get("tables", []):
            flds = t.get("fields", [])
            data = t.get("data", [])
            if "收盤價" not in flds or "證券代號" not in flds or len(data) < 500:
                continue
            idx = {name: i for i, name in enumerate(flds)}
            for r in data:
                sid = str(r[idx["證券代號"]]).strip()
                if not _STOCK_RE.match(sid):
                    continue
                vol = _num(r[idx["成交股數"]]) or 0
                amt = _num(r[idx["成交金額"]]) or 0
                rows.append({
                    "date": target_date,
                    "stock_id": sid,
                    "open": _num(r[idx["開盤價"]]),
                    "high": _num(r[idx["最高價"]]),
                    "low": _num(r[idx["最低價"]]),
                    "close": _num(r[idx["收盤價"]]),
                    # 均價＝成交金額÷成交股數（當日實際成交均價，非 OHLC 算術平均）
                    "avg_price": (amt / vol) if vol else None,
                    "volume": int(vol),
                    "turnover": int(amt),
                    "market": "twse",
                })
            break
        return rows

    def save(self, rows: list[dict]) -> int:
        return self.upsert(RawStockPrice, rows, ["date", "stock_id"])

    # ── 上櫃（TPEx OpenAPI）──────────────────────────────────────────────
    def collect_otc(self, target_date: date) -> int:
        """上櫃逐檔行情 — TPEx OpenAPI。

        ※ 只有「當日」資料，無法回補歷史（CHIP 既有教訓）。
        ※ TPEx 憑證缺 Subject Key Identifier，需 ssl.CERT_NONE（比照 tpex_chip.py）。
        本 dataset 直接提供 Average（當日均價），不必自行由成交金額推算。
        """
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(f"{_TPEX_BASE}/tpex_mainboard_daily_close_quotes",
                                     headers={"User-Agent": "Mozilla/5.0"})
        data = _json.load(urllib.request.urlopen(req, timeout=60, context=ctx))

        rows, seen = [], set()
        for d in data:
            sid = str(d.get("SecuritiesCompanyCode") or "").strip()
            if not _STOCK_RE.match(sid) or sid in seen:
                continue
            roc = str(d.get("Date") or "").strip()          # 民國 YYYMMDD，如 1150720
            if len(roc) != 7:
                continue
            try:
                row_date = date(int(roc[:3]) + 1911, int(roc[3:5]), int(roc[5:7]))
            except ValueError:
                continue
            if row_date != target_date:                     # 只收目標日，避免混入他日
                continue
            seen.add(sid)
            vol = _num(d.get("TradingShares")) or 0
            amt = _num(d.get("TransactionAmount")) or 0
            rows.append({
                "date": target_date, "stock_id": sid,
                "open": _num(d.get("Open")), "high": _num(d.get("High")),
                "low": _num(d.get("Low")), "close": _num(d.get("Close")),
                "avg_price": _num(d.get("Average")) or ((amt / vol) if vol else None),
                "volume": int(vol), "turnover": int(amt), "market": "otc",
            })
        if not rows:
            self.log.warning("TPEx 無 %s 的上櫃行情（非交易日或尚未發布）", target_date)
            return 0
        n = self.upsert(RawStockPrice, rows, ["date", "stock_id"])
        self.db.commit()
        return n

    def collect_all(self, target_date: date) -> dict:
        """上市＋上櫃一起收。回 {'twse': n, 'otc': n}。"""
        out = {}
        try:
            out["twse"] = self.collect(target_date)
        except Exception as e:  # noqa: BLE001
            out["twse"] = f"error: {e}"
        try:
            out["otc"] = self.collect_otc(target_date)
        except Exception as e:  # noqa: BLE001
            out["otc"] = f"error: {e}"
        return out
