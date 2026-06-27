"""券商分點進出 — TPEx 上櫃股票

新版 API（2024+ Cloudflare 保護後）：
  由瀏覽器端帶 Turnstile token fetch CSV，後端呼叫 parse_csv_text() 解析。
  舊 JSON endpoint (brokerBS_result.php) 已廢棄（soft 404）。

CSV 格式：
  行0: 券商買賣證券成交價量資訊
  行1: 證券代碼,XXXX
  行2: 序號,券商,價格,買進股數,賣出股數
  行3+: "1","1020 合庫","2310","0","1000"

  券商欄格式：4碼 branch_id + 空格 + 券商名稱
  單位：股(÷1000=張)，元(×stocks÷1000=千元)
"""
from __future__ import annotations

import csv
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


def _to_roc_date(d: date) -> str:
    return f"{d.year - 1911}/{d.month:02d}/{d.day:02d}"


def parse_csv_text(csv_text: str, target_date: date, stock_id: str) -> list[dict]:
    """解析 TPEx brokerBS CSV（新版 Cloudflare 保護後的格式）。

    序號,券商,價格,買進股數,賣出股數
    "1","1020 合庫","2310","0","1000"

    Returns list of dicts for RawBrokerChips upsert.
    """
    lines = csv_text.splitlines()
    data_start = 0
    for i, line in enumerate(lines):
        if line.strip().strip('"').startswith("序號"):
            data_start = i + 1
            break
    if data_start == 0:
        return []

    agg: dict[str, dict] = {}
    reader = csv.reader(lines[data_start:])
    for parts in reader:
        if len(parts) < 5:
            continue
        broker_raw = parts[1].strip()
        if not broker_raw:
            continue
        sp = broker_raw.split(" ", 1)
        branch_id   = sp[0].strip()
        branch_name = sp[1].strip() if len(sp) > 1 else broker_raw
        if not branch_id:
            continue
        try:
            price   = float(parts[2].replace(",", "").strip() or "0")
            buy_sh  = _clean_int(parts[3])
            sell_sh = _clean_int(parts[4])
        except (ValueError, IndexError):
            continue
        if branch_id not in agg:
            agg[branch_id] = {"name": branch_name, "buy": 0.0, "sell": 0.0, "bval": 0.0, "sval": 0.0}
        rec = agg[branch_id]
        if branch_name:
            rec["name"] = branch_name
        rec["buy"]  += buy_sh
        rec["sell"] += sell_sh
        rec["bval"] += buy_sh  * price
        rec["sval"] += sell_sh * price

    result = []
    for bid, rec in agg.items():
        result.append({
            "date":        target_date,
            "stock_id":    stock_id,
            "branch_id":   bid,
            "branch_name": rec["name"],
            "buy_volume":  int(rec["buy"])  // 1000,
            "sell_volume": int(rec["sell"]) // 1000,
            "buy_value":   int(rec["bval"]) // 1000,
            "sell_value":  int(rec["sval"]) // 1000,
        })
    return result


class TpexBrokerChipsCollector(BaseCollector):
    name = "tpex_broker_chips"

    def fetch(self, target_date: date) -> dict:
        return {}

    def parse(self, raw: dict, target_date: date) -> list[dict]:
        return []

    def save(self, rows: list[dict]) -> int:
        return self.upsert(RawBrokerChips, rows, ["date", "stock_id", "branch_id"])

    # ── Main entry point ──────────────────────────────────────────────────

    def collect_stocks(self, target_date: date, stock_ids: list[str] | None = None) -> int:
        """Collect TPEx broker chips for OTC stocks."""
        from app.core.config import settings

        if stock_ids is None:
            stock_ids = [
                s.stock_id for s in
                self.db.query(Stock)
                .filter(Stock.market == "otc", Stock.is_active == True)
                .all()
            ]

        total = 0
        roc_date = _to_roc_date(target_date)
        url = f"{settings.TPEX_BASE_URL}/web/stock/aftertrading/broker_trading/brokerBS_result.php"

        for stock_id in stock_ids:
            try:
                resp = self.get(
                    url,
                    params={"l": "zh-tw", "d": roc_date, "stkno": stock_id, "t": "D"},
                    referer=f"{settings.TPEX_BASE_URL}/web/stock/aftertrading/broker_trading/brokerBS.php",
                )
                data = resp.json()
                rows = self._parse_single(data, target_date, stock_id)
                if rows:
                    self.upsert(RawBrokerChips, rows, ["date", "stock_id", "branch_id"])
                    total += len(rows)
            except Exception as e:
                self.log.warning("tpex broker chips failed for %s: %s", stock_id, e)
                continue

        self.db.commit()
        self.log.info("tpex broker chips: %d rows for %d stocks on %s", total, len(stock_ids), target_date)
        return total

    def _parse_single(self, raw: dict, target_date: date, stock_id: str) -> list[dict]:
        """Parse TPEx brokerBS_result.php response.

        aaData columns: [branch_id, branch_name, buy_shares, buy_amount, sell_shares, sell_amount]
        Units: shares (股) and NT$ (元) → divide by 1000 → 張 / 千元
        """
        aa = raw.get("aaData") or raw.get("data", [])
        if not aa:
            return []

        rows = []
        for row in aa:
            if len(row) < 6:
                continue
            branch_id = str(row[0]).strip()
            branch_name = str(row[1]).strip()
            if not branch_id:
                continue

            buy_shares  = _clean_int(row[2])
            buy_amount  = _clean_int(row[3])
            sell_shares = _clean_int(row[4])
            sell_amount = _clean_int(row[5])

            rows.append({
                "date":         target_date,
                "stock_id":     stock_id,
                "branch_id":    branch_id,
                "branch_name":  branch_name,
                "buy_volume":   buy_shares  // 1000,  # 股 → 張
                "buy_value":    buy_amount  // 1000,  # 元 → 千元
                "sell_volume":  sell_shares // 1000,
                "sell_value":   sell_amount // 1000,
            })
        return rows
