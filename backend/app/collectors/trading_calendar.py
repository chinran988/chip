"""Populate trading_calendar from TWSE holiday schedule API."""
from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.collectors.base import BaseCollector
from app.models.reference import TradingCalendar

logger = logging.getLogger(__name__)


class TradingCalendarCollector(BaseCollector):
    name = "trading_calendar"

    def fetch(self, target_date: date) -> list[dict]:
        """Fetch holiday list for the year of target_date."""
        year = target_date.year
        url = f"{settings.TWSE_BASE_URL}/holidaySchedule/holidaySchedule"
        resp = self.get(url, params={"response": "json", "year": str(year)},
                        referer=settings.TWSE_BASE_URL)
        data = resp.json()
        return data.get("data", [])

    def parse(self, raw: list[dict], target_date: date) -> list[dict]:
        holidays: set[date] = set()
        for row in raw:
            try:
                # TWSE format: ["113/01/01", "元旦", ...]
                date_str = row[0].strip()   # e.g. "113/01/01" (ROC calendar)
                parts = date_str.split("/")
                yr = int(parts[0]) + 1911
                mo = int(parts[1])
                dy = int(parts[2])
                holidays.add(date(yr, mo, dy))
            except Exception:
                continue
        return [{"date": d, "is_trading_day": d not in holidays}
                for d in holidays]

    def save(self, rows: list[dict]) -> int:
        return self.upsert(TradingCalendar, rows, ["date"])

    # ── Convenience: fill a whole year ───────────────────────────────────

    def fill_year(self, year: int) -> int:
        """Populate every calendar day for `year`, marking weekends + holidays."""
        sample = date(year, 6, 1)
        holidays_rows = self.fetch(sample)
        holidays_parsed = self.parse(holidays_rows, sample)
        holiday_dates = {r["date"] for r in holidays_parsed if not r["is_trading_day"]}

        rows = []
        d = date(year, 1, 1)
        while d.year == year:
            is_weekend = d.weekday() >= 5
            is_holiday = d in holiday_dates
            rows.append({"date": d, "is_trading_day": not (is_weekend or is_holiday)})
            d += timedelta(days=1)

        count = self.upsert(TradingCalendar, rows, ["date"])
        self.db.commit()
        return count

    def is_trading_day(self, d: date) -> bool:
        row = self.db.get(TradingCalendar, d)
        if row is None:
            # Fallback: assume weekdays are trading days
            return d.weekday() < 5
        return row.is_trading_day
