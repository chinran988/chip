"""券商分點進出 — TWSE BSR 買賣日報表 (bsContent.aspx).

流程：
  1. GET bsMenu.aspx → 取 VIEWSTATE + CAPTCHA guid
  2. ddddocr 自動辨識 CAPTCHA
  3. POST bsMenu.aspx 帶 stock_id + CAPTCHA 答案
  4. GET bsContent.aspx?v=t&StkNo=X&RecCount=9999 → 解析 HTML table
  5. 彙總每券商 buy/sell → upsert raw_broker_chips
  6. 30±5 秒後下一支

資料粒度：每券商每成交價一列 → 彙總後含加權均買/均賣價。
注意：BSR 只有當日資料，無歷史。
"""
from __future__ import annotations

import random
import re
import sys
import time
from datetime import date
from typing import Iterator

import ddddocr
import requests
from sqlalchemy.orm import Session

from app.collectors.base import BaseCollector
from app.models.raw import RawBrokerChips
from app.models.reference import Stock

_BSR = "https://bsr.twse.com.tw/bshtm"
_DELAY_BASE  = 30.0
_DELAY_JITTER = 5.0
_MAX_CAPTCHA_RETRY = 8

_ocr: ddddocr.DdddOcr | None = None


def _get_ocr() -> ddddocr.DdddOcr:
    global _ocr
    if _ocr is None:
        _ocr = ddddocr.DdddOcr(show_ad=False)
    return _ocr


def _clean_num(s: str) -> float:
    try:
        return float(str(s).replace(",", "").strip() or "0")
    except ValueError:
        return 0.0


def _parse_html(html: str) -> tuple[str, list[tuple[str, str, float, float, float]]]:
    """解析 bsContent.aspx HTML，回傳 (stock_id, [(branch_id, name, price, buy, sell)])。"""
    # 股票代號
    sid_m = re.search(r"id='stock_id'>\s*(\d+)", html)
    stock_id = sid_m.group(1) if sid_m else ""

    # 資料列：column_value_left = 券商, 接下來3個 column_value_right = 價, 買, 賣
    row_pat = re.compile(
        r"column_value_left[^>]*>\s*([\dA-Za-z]{4})([^<]*?)</td>"  # broker_id + name
        r"(?:(?!</td>).)*?column_value_right[^>]*>\s*([\d,\.]+)</td>"  # price
        r"(?:(?!</td>).)*?column_value_right[^>]*>\s*([\d,]+)</td>"    # buy shares
        r"(?:(?!</td>).)*?column_value_right[^>]*>\s*([\d,]+)</td>",   # sell shares
        re.DOTALL,
    )
    rows = []
    for m in row_pat.finditer(html):
        bid   = m.group(1).strip()
        bname = m.group(2).strip()
        price = _clean_num(m.group(3))
        buy   = _clean_num(m.group(4))
        sell  = _clean_num(m.group(5))
        rows.append((bid, bname, price, buy, sell))
    return stock_id, rows


def _aggregate(rows: list[tuple], target_date: date, stock_id: str) -> list[dict]:
    """GROUP BY broker，計算買賣量(張)、金額(千元)。"""
    agg: dict[str, dict] = {}
    for bid, bname, price, buy_sh, sell_sh in rows:
        if bid not in agg:
            agg[bid] = {"name": bname, "buy": 0.0, "sell": 0.0, "bval": 0.0, "sval": 0.0}
        rec = agg[bid]
        if bname:
            rec["name"] = bname
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


class BsrBrokerChipsCollector(BaseCollector):
    """BSR 買賣日報表全量採集器（ddddocr 自動過 CAPTCHA）。"""

    name = "bsr_broker_chips"

    def __init__(self, db: Session):
        super().__init__(db)
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer":    f"{_BSR}/",
        })

    # ── BaseCollector stubs ──────────────────────────────────────────────
    def fetch(self, target_date: date) -> dict:   return {}
    def parse(self, raw: dict, target_date: date) -> list[dict]: return []
    def save(self, rows: list[dict]) -> int:
        return self.upsert(RawBrokerChips, rows, ["date", "stock_id", "branch_id"])

    # ── BSR 專用 throttle：30±5 秒 ──────────────────────────────────────
    def _throttle(self) -> None:
        delay = _DELAY_BASE + random.uniform(-_DELAY_JITTER, _DELAY_JITTER)
        self.log.debug("BSR throttle %.1f s", delay)
        time.sleep(delay)

    # ── 主入口 ───────────────────────────────────────────────────────────
    def collect_stocks(self, target_date: date, stock_ids: list[str] | None = None) -> int:
        if stock_ids is None:
            stock_ids = [
                s.stock_id for s in
                self.db.query(Stock)
                .filter(Stock.market == "twse", Stock.is_active == True)
                .all()
            ]

        total = 0
        for stock_id in stock_ids:
            try:
                rows = self._fetch_one(target_date, stock_id)
                if rows:
                    self.upsert(RawBrokerChips, rows, ["date", "stock_id", "branch_id"])
                    total += len(rows)
                    self.db.commit()
                self._throttle()
            except Exception as e:
                self.log.warning("BSR failed %s: %s", stock_id, e)
                self._throttle()   # 出錯也等，不要狂打

        self.log.info("BSR done: %d broker rows for %d stocks on %s",
                      total, len(stock_ids), target_date)
        return total

    # ── 內部：解 CAPTCHA + 送表單 + 抓資料 ──────────────────────────────
    def _fetch_one(self, target_date: date, stock_id: str) -> list[dict]:
        for attempt in range(_MAX_CAPTCHA_RETRY):
            if attempt > 0:
                # 重試等 5±5 秒（不佔 30 秒主間隔）
                time.sleep(max(0, 5 + random.uniform(-5, 5)))

            try:
                html = self._solve_and_fetch(stock_id)
            except Exception as e:
                self.log.debug("attempt %d error: %s", attempt + 1, e)
                continue

            if len(html) < 5000:
                self.log.debug("attempt %d: response too short (%d)", attempt + 1, len(html))
                continue

            found_sid, price_rows = _parse_html(html)
            if not price_rows:
                # 無資料 = 該股票今日未交易或不在 BSR 收錄範圍，直接跳過
                return []

            return _aggregate(price_rows, target_date, stock_id)

        self.log.warning("BSR %s: CAPTCHA failed after %d attempts", stock_id, _MAX_CAPTCHA_RETRY)
        return []

    def _solve_and_fetch(self, stock_id: str) -> str:
        s = self._session

        # 1. GET bsMenu.aspx
        r = s.get(f"{_BSR}/bsMenu.aspx", timeout=20)
        r.raise_for_status()

        vs    = re.search(r'id="__VIEWSTATE"[^>]*value="([^"]+)"',          r.text)
        vsgen = re.search(r'id="__VIEWSTATEGENERATOR"[^>]*value="([^"]+)"', r.text)
        evval = re.search(r'id="__EVENTVALIDATION"[^>]*value="([^"]+)"',    r.text)
        guid  = re.search(r'CaptchaImage\.aspx\?guid=([\w\-]+)',             r.text)

        if not all([vs, vsgen, evval, guid]):
            raise RuntimeError("missing hidden fields")

        # 2. 辨識 CAPTCHA
        img_bytes = s.get(
            f"{_BSR}/CaptchaImage.aspx?guid={guid.group(1)}", timeout=10
        ).content
        answer = _get_ocr().classification(img_bytes)
        self.log.debug("CAPTCHA answer: '%s'", answer)

        # 3. POST 表單
        post = {
            "__VIEWSTATE":          vs.group(1),
            "__VIEWSTATEGENERATOR": vsgen.group(1),
            "__EVENTVALIDATION":    evval.group(1),
            "__EVENTTARGET":        "",
            "__EVENTARGUMENT":      "",
            "RadioButton_Normal":   "RadioButton_Normal",
            "TextBox_Stkno":        stock_id,
            "CaptchaControl1":      answer,
            "btnOK":                "查詢",
        }
        r2 = s.post(f"{_BSR}/bsMenu.aspx", data=post,
                    headers={"Referer": f"{_BSR}/bsMenu.aspx"}, timeout=20)
        r2.raise_for_status()

        if "驗證碼" in r2.text:
            raise RuntimeError(f"wrong CAPTCHA '{answer}'")

        # 4. 取資料頁
        rc = s.get(f"{_BSR}/bsContent.aspx",
                   params={"v": "t", "StkNo": stock_id, "RecCount": "9999"},
                   headers={"Referer": f"{_BSR}/bsMenu.aspx"}, timeout=30)
        rc.raise_for_status()
        return rc.text
