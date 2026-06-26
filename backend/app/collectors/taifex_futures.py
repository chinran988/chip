"""期貨三大法人未平倉 — TAIFEX 大額交易人未沖銷部位報告.

TAIFEX endpoint: POST /cht/3/futContractsDate
Form fields:
  queryDate   = YYYY/MM/DD
  commodityId = TXF | MXF (or empty for all)

Response: HTML page with a multi-level-header table.
Column layout (after pd.read_html with multi-level columns):
  col 2  = 身份別 (identity: 自營商 / 投信 / 外資)
  col 9  = 未平倉 多方 口數 (OI long contracts)
  col 11 = 未平倉 空方 口數 (OI short contracts)

Rows 0-2 are individual institutions; rows 3-5 are 期貨小計 (duplicate).
We take rows 0-2 (or any row matching the identity string before "小計").
"""
from __future__ import annotations

import io
from datetime import date

import pandas as pd

from app.collectors.base import BaseCollector
from app.models.raw import RawFuturesOI

_PAGE_URL = "https://www.taifex.com.tw/cht/3/futContractsDate"

# Contract mapping: (our name, TAIFEX commodityId)
CONTRACTS = [
    ("TXF", "TXF"),   # 臺股期貨大台
    ("MXF", "MXF"),   # 小型臺指期貨
]

# Column indices in the flattened DataFrame (0-indexed after multi-level collapse)
_COL_IDENTITY = 2
_COL_OI_LONG  = 9
_COL_OI_SHORT = 11


def _clean_int(val) -> int:
    try:
        return int(str(val).replace(",", "").strip() or "0")
    except (ValueError, TypeError):
        return 0


class FuturesOICollector(BaseCollector):
    name = "taifex_futures"

    def _get_session_cookies(self) -> None:
        """GET the page first to acquire JSESSIONID and ROUTEID cookies."""
        from app.collectors.base import _SESSION
        _SESSION.get(_PAGE_URL, timeout=20)

    def fetch(self, target_date: date) -> dict[str, str]:
        """Return dict of {contract_name: html_text}."""
        self._get_session_cookies()
        from app.collectors.base import _SESSION
        date_str = target_date.strftime("%Y/%m/%d")
        results: dict[str, str] = {}
        for our_name, taifex_id in CONTRACTS:
            try:
                resp = _SESSION.post(
                    _PAGE_URL,
                    data={"queryDate": date_str, "commodityId": taifex_id},
                    headers={"Referer": _PAGE_URL,
                             "Content-Type": "application/x-www-form-urlencoded"},
                    timeout=30,
                )
                resp.raise_for_status()
                self._throttle()
                results[our_name] = resp.text
            except Exception as e:
                self.log.warning("TAIFEX fetch failed for %s: %s", our_name, e)
                results[our_name] = ""
        return results

    def parse(self, raw: dict[str, str], target_date: date) -> list[dict]:
        rows: list[dict] = []
        for contract, html in raw.items():
            if not html or "查無資料" in html:
                self.log.debug("No TAIFEX data for %s on %s", contract, target_date)
                continue
            try:
                tables = pd.read_html(io.StringIO(html))
            except Exception as e:
                self.log.warning("TAIFEX HTML parse error for %s: %s", contract, e)
                continue

            # Find the table with institution rows (>= 3 rows, >= 12 cols)
            data_tables = [t for t in tables if t.shape[0] >= 3 and t.shape[1] >= 12]
            if not data_tables:
                self.log.warning("TAIFEX no data table found for %s on %s", contract, target_date)
                continue

            df = data_tables[0]
            agg = {"foreign_long": 0, "foreign_short": 0,
                   "trust_long": 0, "trust_short": 0,
                   "dealer_long": 0, "dealer_short": 0,
                   "oi_total": 0}
            found = False

            for _, row in df.iterrows():
                identity = str(row.iloc[_COL_IDENTITY]).strip()
                # Skip subtotal rows (小計)
                if "小計" in identity or "合計" in identity:
                    continue
                long_v  = _clean_int(row.iloc[_COL_OI_LONG])
                short_v = _clean_int(row.iloc[_COL_OI_SHORT])
                if "自營" in identity or "Dealer" in identity:
                    agg["dealer_long"]  += long_v
                    agg["dealer_short"] += short_v
                    found = True
                elif "投信" in identity or "Trust" in identity:
                    agg["trust_long"]  += long_v
                    agg["trust_short"] += short_v
                    found = True
                elif "外資" in identity or "Foreign" in identity:
                    agg["foreign_long"]  += long_v
                    agg["foreign_short"] += short_v
                    found = True

            if found:
                rows.append({
                    "date": target_date,
                    "contract": contract,
                    "expiry": "all",
                    **agg,
                })
        return rows

    def save(self, rows: list[dict]) -> int:
        return self.upsert(RawFuturesOI, rows, ["date", "contract", "expiry"])
