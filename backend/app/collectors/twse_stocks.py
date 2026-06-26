"""Stock list collector — TWSE OpenAPI (primary) + Sinopac adapter (supplement)."""
from __future__ import annotations

import logging
from datetime import date

from sqlalchemy.orm import Session

from app.core.config import settings
from app.collectors.base import BaseCollector
from app.models.reference import Stock

logger = logging.getLogger(__name__)


class StockListCollector(BaseCollector):
    name = "twse_stocks"

    # ── TWSE OpenAPI ──────────────────────────────────────────────────────

    def fetch(self, target_date: date) -> dict:
        """Fetch listed (TWSE) and OTC (TPEX) stock lists."""
        listed = self._fetch_twse_listed()
        otc = self._fetch_tpex_otc()
        return {"listed": listed, "otc": otc}

    def _fetch_twse_listed(self) -> list[dict]:
        """上市公司基本資料 — TWSE OpenAPI v1."""
        url = f"{settings.TWSE_OPENAPI_URL}/v1/opendata/t187ap03_L"
        try:
            resp = self.get(url, referer=settings.TWSE_BASE_URL)
            return resp.json()
        except Exception as e:
            logger.warning("TWSE OpenAPI listed stocks failed: %s", e)
            return []

    def _fetch_tpex_otc(self) -> list[dict]:
        """上櫃公司基本資料 — TPEX OpenAPI."""
        url = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes"
        try:
            resp = self.get(url, referer="https://www.tpex.org.tw/")
            return resp.json()
        except Exception as e:
            logger.warning("TPEX OTC stocks failed: %s", e)
            return []

    def parse(self, raw: dict, target_date: date) -> list[dict]:
        rows: list[dict] = []

        # TWSE listed
        for item in raw.get("listed", []):
            stock_id = str(item.get("公司代號", "") or item.get("Code", "")).strip()
            if not stock_id or not stock_id.isdigit():
                continue
            rows.append({
                "stock_id": stock_id,
                "name": (item.get("公司簡稱") or item.get("Name", "")).strip(),
                "market": "twse",
                "industry": (item.get("產業別") or item.get("Industry", "")).strip(),
                "industry_code": str(item.get("產業別代號", "") or "").strip(),
                "isin": str(item.get("國際證券辨識號碼", "") or "").strip(),
                "is_active": True,
                "source": "twse",
            })

        # TPEX OTC — different field names
        for item in raw.get("otc", []):
            stock_id = str(item.get("SecuritiesCompanyCode", "") or "").strip()
            if not stock_id or not stock_id.isdigit():
                continue
            if any(r["stock_id"] == stock_id for r in rows):
                continue  # already added
            rows.append({
                "stock_id": stock_id,
                "name": str(item.get("CompanyName", "")).strip(),
                "market": "otc",
                "industry": str(item.get("IndustryName", "")).strip(),
                "industry_code": str(item.get("IndustryCode", "")).strip(),
                "isin": "",
                "is_active": True,
                "source": "tpex",
            })

        return rows

    def save(self, rows: list[dict]) -> int:
        return self.upsert(Stock, rows, ["stock_id"])

    # ── Sinopac supplement ────────────────────────────────────────────────

    def supplement_from_sinopac(self) -> int:
        """Add/update stock entries from the running Shioaji adapter.
        Called after TWSE collection to fill gaps (e.g. ETF, warrants).
        Fails silently if adapter is offline.
        """
        import urllib.request, json
        try:
            url = settings.SINOPAC_ADAPTER_URL + "/contracts/stocks"
            with urllib.request.urlopen(url, timeout=5) as r:
                contracts = json.loads(r.read())
        except Exception as e:
            logger.info("Sinopac adapter not available (%s), skipping supplement", e)
            return 0

        rows = []
        for c in contracts:
            stock_id = str(c.get("code", "")).strip()
            if not stock_id:
                continue
            rows.append({
                "stock_id": stock_id,
                "name": str(c.get("name", "")).strip(),
                "market": "twse" if c.get("exchange", "") == "TSE" else "otc",
                "industry": str(c.get("category", "")).strip(),
                "industry_code": "",
                "isin": "",
                "is_active": True,
                "source": "sinopac",
            })

        if rows:
            count = self.upsert(Stock, rows, ["stock_id"])
            self.db.commit()
            logger.info("Sinopac supplement: %d stocks", count)
            return count
        return 0
