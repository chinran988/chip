"""三大法人買賣超 — TWSE T86 (全市場一次回傳)."""
from __future__ import annotations

import re
from datetime import date

from app.collectors.base import BaseCollector
from app.models.raw import RawInstitutional


def _clean_int(val: str) -> int:
    try:
        return int(str(val).replace(",", "").strip() or "0")
    except ValueError:
        return 0


class InstitutionalCollector(BaseCollector):
    name = "twse_institutional"

    def fetch(self, target_date: date) -> dict:
        from app.core.config import settings
        date_str = target_date.strftime("%Y%m%d")
        url = f"{settings.TWSE_BASE_URL}/fund/T86"
        resp = self.get(
            url,
            params={"response": "json", "date": date_str, "selectType": "ALL"},
            referer=settings.TWSE_BASE_URL,
        )
        return resp.json()

    def parse(self, raw: dict, target_date: date) -> list[dict]:
        status = raw.get("stat", "")
        if status != "OK":
            self.log.warning("T86 stat=%s for %s", status, target_date)
            return []

        data = raw.get("data", [])
        rows = []
        for row in data:
            # T86 columns (0-indexed):
            # 0=股票代號, 1=股票名稱
            # 2=外資買, 3=外資賣, 4=外資淨
            # 5=投信買, 6=投信賣, 7=投信淨
            # 8=自營商買(自行), 9=自營商賣(自行), 10=自營商淨(自行)
            # 11=自營商買(避險), 12=自營商賣(避險), 13=自營商淨(避險)
            # 14=三大法人合計
            if len(row) < 14:
                continue
            stock_id = str(row[0]).strip()
            if not stock_id or not re.match(r"^\d{4,6}$", stock_id):
                continue
            rows.append({
                "date": target_date,
                "stock_id": stock_id,
                "foreign_buy": _clean_int(row[2]),
                "foreign_sell": _clean_int(row[3]),
                "trust_buy": _clean_int(row[5]),
                "trust_sell": _clean_int(row[6]),
                "dealer_buy": _clean_int(row[8]),
                "dealer_sell": _clean_int(row[9]),
                "dealer_hedge_buy": _clean_int(row[11]),
                "dealer_hedge_sell": _clean_int(row[12]),
            })
        return rows

    def save(self, rows: list[dict]) -> int:
        return self.upsert(RawInstitutional, rows, ["date", "stock_id"])
