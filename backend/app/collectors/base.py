"""Base collector class — all collectors inherit from this."""
from __future__ import annotations

import logging
import random
import time
from abc import ABC, abstractmethod
from datetime import date

import requests
from sqlalchemy.orm import Session

from app.core.config import settings

logger = logging.getLogger(__name__)

_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
})


class BaseCollector(ABC):
    name: str = "base"

    def __init__(self, db: Session):
        self.db = db
        self.log = logging.getLogger(f"chip.{self.name}")

    # ── HTTP helpers ──────────────────────────────────────────────────────

    def get(self, url: str, *, referer: str = "", params: dict | None = None, timeout: int = 30) -> requests.Response:
        headers = {"Referer": referer} if referer else {}
        resp = _SESSION.get(url, params=params, headers=headers, timeout=timeout)
        resp.raise_for_status()
        self._throttle()
        return resp

    def post(self, url: str, data: dict, *, referer: str = "", timeout: int = 30) -> requests.Response:
        headers = {"Referer": referer} if referer else {}
        resp = _SESSION.post(url, data=data, headers=headers, timeout=timeout)
        resp.raise_for_status()
        self._throttle()
        return resp

    def _throttle(self) -> None:
        delay = random.uniform(settings.REQUEST_DELAY_MIN, settings.REQUEST_DELAY_MAX)
        time.sleep(delay)

    # ── Template method ───────────────────────────────────────────────────

    def collect(self, target_date: date) -> int:
        """Fetch, parse, validate, upsert.  Returns number of rows saved."""
        self.log.info("collecting %s for %s", self.name, target_date)
        try:
            raw = self.fetch(target_date)
            rows = self.parse(raw, target_date)
            if not rows:
                self.log.warning("no data returned for %s on %s", self.name, target_date)
                return 0
            count = self.save(rows)
            self.db.commit()
            self.log.info("saved %d rows [%s / %s]", count, self.name, target_date)
            return count
        except Exception as exc:
            self.db.rollback()
            self.log.error("collect failed [%s / %s]: %s", self.name, target_date, exc, exc_info=True)
            raise

    @abstractmethod
    def fetch(self, target_date: date) -> object:
        """Download raw data for target_date."""

    @abstractmethod
    def parse(self, raw: object, target_date: date) -> list[dict]:
        """Parse raw response into list of dicts matching ORM model columns."""

    @abstractmethod
    def save(self, rows: list[dict]) -> int:
        """Upsert rows into DB.  Returns number of rows affected."""

    # ── Shared upsert helper ──────────────────────────────────────────────

    def upsert(self, model, rows: list[dict], conflict_cols: list[str]) -> int:
        """INSERT OR REPLACE based on conflict_cols.
        Batches to respect SQLite's 999 bound-parameter limit.
        """
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        if not rows:
            return 0
        # SQLite max variables = 999; batch size = floor(999 / n_cols)
        n_cols = len(rows[0])
        batch_size = max(1, 999 // n_cols)
        total = 0
        for i in range(0, len(rows), batch_size):
            chunk = rows[i: i + batch_size]
            stmt = sqlite_insert(model).values(chunk)
            update_cols = {c: stmt.excluded[c] for c in chunk[0] if c not in conflict_cols}
            stmt = stmt.on_conflict_do_update(index_elements=conflict_cols, set_=update_cols)
            result = self.db.execute(stmt)
            total += result.rowcount
        return total
