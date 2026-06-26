"""融資融券餘額 — TWSE MI_MARGN (全市場一次回傳).

Response format (as of 2026):
  {"stat": "OK", "date": "...", "tables": [summary_table, per_stock_table]}
  tables[1] = 融資融券彙總 per-stock rows.

Column layout of tables[1].data rows:
  0=代號, 1=名稱
  2=融資買進, 3=融資賣出, 4=融資現金償還, 5=融資前日餘額, 6=融資今日餘額, 7=融資限額
  8=融券買進, 9=融券賣出, 10=融券現券償還, 11=融券前日餘額, 12=融券今日餘額, 13=融券限額
  14=資券互抵, 15=註記
"""
from __future__ import annotations

import re
from datetime import date

from app.collectors.base import BaseCollector
from app.models.raw import RawMargin

# Accept standard 4-6 digit codes plus ETF codes with trailing letter (e.g. 00400A)
_STOCK_RE = re.compile(r"^\d{4,6}[A-Z]?$")


def _clean_int(val: str) -> int:
    try:
        return int(str(val).replace(",", "").strip() or "0")
    except ValueError:
        return 0


class MarginCollector(BaseCollector):
    name = "twse_margin"

    def fetch(self, target_date: date) -> dict:
        from app.core.config import settings
        date_str = target_date.strftime("%Y%m%d")
        resp = self.get(
            f"{settings.TWSE_BASE_URL}/exchangeReport/MI_MARGN",
            params={"response": "json", "date": date_str, "selectType": "ALL"},
            referer=settings.TWSE_BASE_URL,
        )
        return resp.json()

    def parse(self, raw: dict, target_date: date) -> list[dict]:
        if raw.get("stat") != "OK":
            self.log.warning("MI_MARGN stat=%s for %s", raw.get("stat"), target_date)
            return []

        # Data is in tables[1] (per-stock table); tables[0] is the market aggregate summary
        tables = raw.get("tables", [])
        per_stock_rows = tables[1].get("data", []) if len(tables) > 1 else []
        if not per_stock_rows:
            self.log.warning("MI_MARGN tables[1] empty for %s", target_date)
            return []

        rows = []
        for row in per_stock_rows:
            if len(row) < 13:
                continue
            stock_id = str(row[0]).strip()
            if not stock_id or not _STOCK_RE.match(stock_id):
                continue
            rows.append({
                "date": target_date,
                "stock_id": stock_id,
                "margin_buy": _clean_int(row[2]),
                "margin_sell": _clean_int(row[3]),
                "margin_balance": _clean_int(row[6]),
                "margin_limit": _clean_int(row[7]),
                "short_sell": _clean_int(row[9]),
                "short_buy": _clean_int(row[8]),
                "short_balance": _clean_int(row[12]),
                "short_limit": _clean_int(row[13]) if len(row) > 13 else 0,
            })
        return rows

    def save(self, rows: list[dict]) -> int:
        return self.upsert(RawMargin, rows, ["date", "stock_id"])
