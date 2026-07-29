"""上櫃籌碼 — TPEx 三大法人 + 融資融券（公開 OpenAPI，純後端直連）。

- 三大法人：/openapi/v1/tpex_3insti_daily_trading  → raw_institutional
- 融資融券：/openapi/v1/tpex_mainboard_margin_balance → raw_margin

TPEx OpenAPI 憑證缺 Subject Key Identifier，需 ssl.CERT_NONE。
欄位名含不一致空格，用模糊關鍵字匹配容錯。
"""
from __future__ import annotations

import ssl
import json
import urllib.request
from datetime import date

from sqlalchemy.orm import Session

from app.collectors.base import BaseCollector
from app.models.raw import RawInstitutional, RawMargin

_BASE = "https://www.tpex.org.tw/openapi/v1"


def _ctx() -> ssl.SSLContext:
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def _fetch(name: str) -> list[dict]:
    req = urllib.request.Request(f"{_BASE}/{name}", headers={"User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(req, timeout=60, context=_ctx()))


def _num(v) -> int:
    try:
        return int(float(str(v).replace(",", "").strip() or "0"))
    except (ValueError, TypeError):
        return 0


def _find(row: dict, *keywords: str) -> int:
    """回傳第一個 key 同時包含所有 include keyword、且不含任何 !exclude keyword 的值（不分大小寫/空格）。

    以 "!xxx" 傳入排除關鍵字。用來解 TPEx OpenAPI 欄名撞名：
    「Foreign Investors …(Foreign Dealers excluded)」同時含 "Dealers"，
    若不排除會被 dealer 匹配誤抓、外資也會被重複相加（2026-07-29 修正）。
    """
    incl = [k.replace(" ", "").lower() for k in keywords if not k.startswith("!")]
    excl = [k[1:].replace(" ", "").lower() for k in keywords if k.startswith("!")]
    for k, v in row.items():
        kk = k.replace(" ", "").lower()
        if all(w in kk for w in incl) and not any(w in kk for w in excl):
            return _num(v)
    return 0


def _roc_to_iso(roc: str) -> date | None:
    # "1150715" → 2026-07-15
    s = str(roc).strip()
    if len(s) != 7 or not s.isdigit():
        return None
    return date(int(s[:3]) + 1911, int(s[3:5]), int(s[5:7]))


class TpexChipCollector(BaseCollector):
    """上櫃三大法人 + 融資融券採集器。"""

    name = "tpex_chip"

    def fetch(self, target_date: date) -> dict: return {}
    def parse(self, raw: dict, target_date: date) -> list[dict]: return []
    def save(self, rows: list[dict]) -> int: return 0

    # ── 三大法人 ─────────────────────────────────────────────────────────
    def collect_institutional(self, target_date: date) -> int:
        data = _fetch("tpex_3insti_daily_trading")
        rows = []
        for r in data:
            d = _roc_to_iso(r.get("Date"))
            if d != target_date:
                continue
            sid = str(r.get("SecuritiesCompanyCode", "")).strip()
            if not sid:
                continue
            # 外資 = 外資及陸資「合計」欄（OpenAPI 已含自營；勿用「不含自營」再自行相加，
            #   舊寫法因欄名含 "Foreign Dealers excluded" 被 ForeignDealers 二次命中→外資翻倍）
            foreign_buy  = _find(r, "ForeignInvestorsInclude", "TotalBuy",  "!excluded", "!Dealers")
            foreign_sell = _find(r, "ForeignInvestorsInclude", "TotalSell", "!excluded", "!Dealers")
            rows.append({
                "date": target_date, "stock_id": sid,
                "foreign_buy": foreign_buy, "foreign_sell": foreign_sell,
                "trust_buy":  _find(r, "InvestmentTrust", "TotalBuy"),
                "trust_sell": _find(r, "InvestmentTrust", "TotalSell"),
                # 自營商合計；排除 Foreign 以免抓到「Foreign Dealers excluded」欄（舊 bug=dealer 抄成外資）
                "dealer_buy":  _find(r, "Dealers", "TotalBuy",  "!Foreign", "!excluded"),
                "dealer_sell": _find(r, "Dealers", "TotalSell", "!Foreign", "!excluded"),
                "dealer_hedge_buy": 0, "dealer_hedge_sell": 0,
            })
        if rows:
            self.upsert(RawInstitutional, rows, ["date", "stock_id"])
            self.db.commit()
        self.log.info("TPEx 三大法人: %d 支 on %s", len(rows), target_date)
        return len(rows)

    # ── 融資融券 ─────────────────────────────────────────────────────────
    def collect_margin(self, target_date: date) -> int:
        data = _fetch("tpex_mainboard_margin_balance")
        rows = []
        for r in data:
            d = _roc_to_iso(r.get("Date"))
            if d != target_date:
                continue
            sid = str(r.get("SecuritiesCompanyCode", "")).strip()
            if not sid:
                continue
            rows.append({
                "date": target_date, "stock_id": sid,
                "margin_buy":     _num(r.get("MarginPurchase")),
                "margin_sell":    _num(r.get("MarginSales")),
                "margin_balance": _num(r.get("MarginPurchaseBalance")),
                "margin_limit":   _num(r.get("MarginPurchaseQuota")),
                "short_sell":     _num(r.get("ShortSale")),
                "short_buy":      _num(r.get("ShortConvering")),
                "short_balance":  _num(r.get("ShortSaleBalance")),
                "short_limit":    _num(r.get("ShortSaleQuota")),
            })
        if rows:
            self.upsert(RawMargin, rows, ["date", "stock_id"])
            self.db.commit()
        self.log.info("TPEx 融資融券: %d 支 on %s", len(rows), target_date)
        return len(rows)

    def collect_all(self, target_date: date) -> dict:
        return {
            "tpex_institutional": self.collect_institutional(target_date),
            "tpex_margin": self.collect_margin(target_date),
        }
