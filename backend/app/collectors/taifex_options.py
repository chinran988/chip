"""選擇權資料採集 — TAIFEX OpenAPI (openapi.taifex.com.tw/v1).

採集 5 個 endpoint：
  /DailyMarketReportOpt                                                  → raw_options_chain
  /MarketDataOfMajorInstitutionalTradersDetailsOfCallsAndPutsBytheDate   → raw_options_institutional
  /MarketDataOfMajorInstitutionalTradersDividedByFuturesAndOptionsBytheDate → raw_options_inst_fo
  /OpenInterestOfLargeTradersOptions                                     → raw_options_large_traders
  /PutCallRatio                                                           → raw_put_call_ratio (22天)
"""
from __future__ import annotations

import json
import logging
from datetime import date

import requests

from app.collectors.base import BaseCollector
from app.models.raw import (
    RawOptionsChain,
    RawOptionsInstitutional,
    RawOptionsInstFO,
    RawOptionsLargeTraders,
    RawPutCallRatio,
)

logger = logging.getLogger(__name__)
_BASE = "https://openapi.taifex.com.tw/v1"
_HEADERS = {
    "Accept": "application/json, */*",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
}


def _si(v) -> int:
    try:
        return int(str(v).replace(",", "").strip())
    except Exception:
        return 0


def _sf(v) -> float | None:
    s = str(v).replace(",", "").strip()
    if s in ("-", "", "nan", "None"):
        return None
    try:
        return float(s)
    except Exception:
        return None


def _parse_date(s: str) -> date | None:
    s = str(s).strip()
    if len(s) == 8 and s.isdigit():
        try:
            return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
        except Exception:
            pass
    return None


def _fetch_json(endpoint: str) -> list[dict]:
    resp = requests.get(f"{_BASE}{endpoint}", headers=_HEADERS, timeout=60)
    resp.raise_for_status()
    return json.loads(resp.content.decode("utf-8"))


class TaifexOptionsCollector(BaseCollector):
    name = "taifex_options"

    # ── 主入口：覆寫 collect()，忽略 target_date（日期來自回應資料）──────────

    def collect(self, target_date: date | None = None) -> dict[str, int]:
        results: dict[str, int] = {}
        for method_name, label in [
            ("_collect_chain",       "chain"),
            ("_collect_institutional", "institutional"),
            ("_collect_inst_fo",     "inst_fo"),
            ("_collect_large_traders","large_traders"),
            ("_collect_pcr",         "put_call_ratio"),
        ]:
            try:
                count = getattr(self, method_name)()
                results[label] = count
            except Exception as e:
                self.log.error("[%s] %s failed: %s", self.name, label, e, exc_info=True)
                results[label] = -1
        return results

    # ── 必要 abstract 方法（不走 BaseCollector 的 collect() 流程）────────────

    def fetch(self, target_date: date):
        return None

    def parse(self, raw, target_date: date) -> list[dict]:
        return []

    def save(self, rows: list[dict]) -> int:
        return 0

    # ── 選擇權鏈 ─────────────────────────────────────────────────────────────

    def _collect_chain(self) -> int:
        data = _fetch_json("/DailyMarketReportOpt")
        rows = []
        for r in data:
            d = _parse_date(r.get("Date", ""))
            if not d:
                continue
            try:
                strike = int(str(r.get("StrikePrice", "0")).replace(",", "").strip())
            except Exception:
                strike = 0
            session_raw = str(r.get("TradingSession", "")).strip()
            rows.append({
                "date":             d,
                "contract":         str(r.get("Contract", "")).strip(),
                "expiry":           str(r.get("ContractMonth(Week)", "")).strip(),
                "strike":           strike,
                "call_put":         str(r.get("CallPut", "")).strip(),
                "trading_session":  "盤後" if session_raw == "盤後" else "一般",
                "open":             _sf(r.get("Open")),
                "high":             _sf(r.get("High")),
                "low":              _sf(r.get("Low")),
                "close":            _sf(r.get("Close")),
                "volume":           _si(r.get("Volume")),
                "settlement_price": _sf(r.get("SettlementPrice")),
                "open_interest":    _si(r.get("OpenInterest")),
                "best_bid":         _sf(r.get("BestBid")),
                "best_ask":         _sf(r.get("BestAsk")),
            })
        if not rows:
            return 0
        count = self.upsert(RawOptionsChain, rows,
                            ["date", "contract", "expiry", "strike", "call_put", "trading_session"])
        self.db.commit()
        self.log.info("[taifex_options] chain: %d rows", count)
        return count

    # ── 三大法人 Call/Put 分計 ────────────────────────────────────────────────

    def _collect_institutional(self) -> int:
        data = _fetch_json(
            "/MarketDataOfMajorInstitutionalTradersDetailsOfCallsAndPutsBytheDate"
        )
        rows = []
        for r in data:
            d = _parse_date(r.get("Date", ""))
            if not d:
                continue
            rows.append({
                "date":          d,
                "contract_code": str(r.get("ContractCode", "")).strip(),
                "call_put":      str(r.get("CallPut", "")).strip(),
                "institution":   str(r.get("Item", "")).strip(),
                "buy_vol":       _si(r.get("TradingVolume(Long)")),
                "buy_val":       _si(r.get("TradingValue(Long)(Thousands)")),
                "sell_vol":      _si(r.get("TradingVolume(Short)")),
                "sell_val":      _si(r.get("TradingValue(Short)(Thousands)")),
                "net_vol":       _si(r.get("TradingVolume(Net)")),
                "net_val":       _si(r.get("TradingValue(Net)(Thousands)")),
                "oi_long":       _si(r.get("OpenInterest(Long)")),
                "oi_long_val":   _si(r.get("ContractValueofOpenInterest(Long)(Thousands)")),
                "oi_short":      _si(r.get("OpenInterest(Short)")),
                "oi_short_val":  _si(r.get("ContractValueofOpenInterest(Short)(Thousands)")),
                "oi_net":        _si(r.get("OpenInterest(Net)")),
                "oi_net_val":    _si(r.get("ContractValueofOpenInterest(Net)(Thousands)")),
            })
        if not rows:
            return 0
        count = self.upsert(RawOptionsInstitutional, rows,
                            ["date", "contract_code", "call_put", "institution"])
        self.db.commit()
        self.log.info("[taifex_options] institutional: %d rows", count)
        return count

    # ── 三大法人期貨/選擇權合計 ──────────────────────────────────────────────

    def _collect_inst_fo(self) -> int:
        data = _fetch_json(
            "/MarketDataOfMajorInstitutionalTradersDividedByFuturesAndOptionsBytheDate"
        )
        rows = []
        for r in data:
            d = _parse_date(r.get("Date", ""))
            if not d:
                continue
            rows.append({
                "date":            d,
                "institution":     str(r.get("Item", "")).strip(),
                "fut_buy_vol":     _si(r.get("FuturesTradingVolume(Long)")),
                "opt_buy_vol":     _si(r.get("OptionsTradingVolume(Long)")),
                "fut_buy_val":     _si(r.get("FuturesTradingValue(Long)(Thousands)")),
                "opt_buy_val":     _si(r.get("OptionsTradingValue(Long)(Thousands)")),
                "fut_sell_vol":    _si(r.get("FuturesTradingVolume(Short)")),
                "opt_sell_vol":    _si(r.get("OptionsTradingVolume(Short)")),
                "fut_sell_val":    _si(r.get("FuturesTradingValue(Short)(Thousands)")),
                "opt_sell_val":    _si(r.get("OptionsTradingValue(Short)(Thousands)")),
                "fut_net_vol":     _si(r.get("FuturesTradingVolume(Net)")),
                "opt_net_vol":     _si(r.get("OptionsTradingVolume(Net)")),
                "fut_net_val":     _si(r.get("FuturesTradingValue(Net)(Thousands)")),
                "opt_net_val":     _si(r.get("OptionsTradingValue(Net)(Thousands)")),
                "fut_oi_long":     _si(r.get("FuturesOpenInterest(Long)")),
                "opt_oi_long":     _si(r.get("OptionsOpenInterest(Long)")),
                "fut_oi_long_val": _si(r.get("FuturesContractValueofOpenInterest(Long)(Thousands)")),
                "opt_oi_long_val": _si(r.get("OptionsContractValueofOpenInterest(Long)(Thousands)")),
                "fut_oi_short":    _si(r.get("FuturesOpenInterest(Short)")),
                "opt_oi_short":    _si(r.get("OptionsOpenInterest(Short)")),
                "fut_oi_short_val":_si(r.get("FuturesContractValueofOpenInterest(Short)(Thousands)")),
                "opt_oi_short_val":_si(r.get("OptionsContractValueofOpenInterest(Short)(Thousands)")),
                "fut_oi_net":      _si(r.get("FuturesOpenInterest(Net)")),
                "opt_oi_net":      _si(r.get("OptionsOpenInterest(Net)")),
                "fut_oi_net_val":  _si(r.get("FuturesContractValueofOpenInterest(Net)(Thousands)")),
                "opt_oi_net_val":  _si(r.get("OptionsContractValueofOpenInterest(Net)(Thousands)")),
            })
        if not rows:
            return 0
        count = self.upsert(RawOptionsInstFO, rows, ["date", "institution"])
        self.db.commit()
        self.log.info("[taifex_options] inst_fo: %d rows", count)
        return count

    # ── 大額交易人未平倉 ──────────────────────────────────────────────────────

    def _collect_large_traders(self) -> int:
        data = _fetch_json("/OpenInterestOfLargeTradersOptions")
        rows = []
        for r in data:
            d = _parse_date(r.get("Date", ""))
            if not d:
                continue
            rows.append({
                "date":             d,
                "contract":         str(r.get("Contract", "")).strip(),
                "contract_name":    str(r.get("ContractName", "")).strip(),
                "call_put":         str(r.get("CallPut", "")).strip(),
                "settlement_month": str(r.get("SettlementMonth", "")).strip(),
                "trader_type":      str(r.get("TypeOfTraders", "")).strip(),
                "top5_buy":         _si(r.get("Top5Buy")),
                "top5_sell":        _si(r.get("Top5Sell")),
                "top10_buy":        _si(r.get("Top10Buy")),
                "top10_sell":       _si(r.get("Top10Sell")),
                "market_oi":        _si(r.get("OIOfMarket")),
            })
        if not rows:
            return 0
        count = self.upsert(RawOptionsLargeTraders, rows,
                            ["date", "contract", "call_put", "settlement_month", "trader_type"])
        self.db.commit()
        self.log.info("[taifex_options] large_traders: %d rows", count)
        return count

    # ── Put/Call Ratio（22 天歷史）────────────────────────────────────────────

    def _collect_pcr(self) -> int:
        data = _fetch_json("/PutCallRatio")
        rows = []
        for r in data:
            d = _parse_date(r.get("Date", ""))
            if not d:
                continue
            rows.append({
                "date":            d,
                "put_volume":      _si(r.get("PutVolume")),
                "call_volume":     _si(r.get("CallVolume")),
                "pc_volume_ratio": _sf(r.get("PutCallVolumeRatio%")),
                "put_oi":          _si(r.get("PutOI")),
                "call_oi":         _si(r.get("CallOI")),
                "pc_oi_ratio":     _sf(r.get("PutCallOIRatio%")),
            })
        if not rows:
            return 0
        count = self.upsert(RawPutCallRatio, rows, ["date"])
        self.db.commit()
        self.log.info("[taifex_options] pcr: %d rows", count)
        return count
