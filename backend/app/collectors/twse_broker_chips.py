"""券商分點進出 — TWSE TWT38U (per-stock query).

Strategy: collect top-N active stocks per day to avoid flooding TWSE.
Full market sweep runs over multiple days (scheduled nightly).
"""
from __future__ import annotations

import re
import time
from datetime import date

from sqlalchemy.orm import Session

from app.collectors.base import BaseCollector
from app.models.raw import RawBrokerChips
from app.models.reference import Stock


def _clean_int(val: str) -> int:
    try:
        return int(str(val).replace(",", "").strip() or "0")
    except ValueError:
        return 0


class BrokerChipsCollector(BaseCollector):
    name = "twse_broker_chips"

    def fetch(self, target_date: date) -> dict:
        # fetch() here is per-stock; batch mode uses collect_stocks()
        return {}

    def parse(self, raw: dict, target_date: date) -> list[dict]:
        return []

    def save(self, rows: list[dict]) -> int:
        return self.upsert(RawBrokerChips, rows, ["date", "stock_id", "branch_id"])

    # ── Main entry point ─────────────────────────────────────────────────

    def collect_stocks(self, target_date: date, stock_ids: list[str] | None = None) -> int:
        """Collect broker chips for a list of stocks (or all active stocks if None).

        Throttles between requests to comply with TWSE rate limits.
        """
        from app.core.config import settings

        if stock_ids is None:
            stock_ids = [s.stock_id for s in
                         self.db.query(Stock).filter(Stock.market == "twse", Stock.is_active == True).all()]

        total = 0
        date_str = target_date.strftime("%Y%m%d")
        url = f"{settings.TWSE_BASE_URL}/exchangeReport/TWT38U"

        for stock_id in stock_ids:
            try:
                resp = self.get(
                    url,
                    params={"response": "json", "date": date_str, "stock_no": stock_id},
                    referer=settings.TWSE_BASE_URL,
                )
                data = resp.json()
                rows = self._parse_single(data, target_date, stock_id)
                if rows:
                    self.upsert(RawBrokerChips, rows, ["date", "stock_id", "branch_id"])
                    total += len(rows)
            except Exception as e:
                self.log.warning("broker chips failed for %s: %s", stock_id, e)
                continue

        self.db.commit()
        self.log.info("broker chips: %d rows for %d stocks on %s", total, len(stock_ids), target_date)
        return total

    def _parse_single(self, raw: dict, target_date: date, stock_id: str) -> list[dict]:
        if raw.get("stat") != "OK":
            return []
        rows = []
        for row in raw.get("data", []):
            if len(row) < 5:
                continue
            branch_id = str(row[0]).strip()
            branch_name = str(row[1]).strip()
            if not branch_id:
                continue
            rows.append({
                "date": target_date,
                "stock_id": stock_id,
                "branch_id": branch_id,
                "branch_name": branch_name,
                "buy_volume": _clean_int(row[2]),
                "buy_value": _clean_int(row[3]),
                "sell_volume": _clean_int(row[4]),
                "sell_value": _clean_int(row[5]) if len(row) > 5 else 0,
            })
        return rows
