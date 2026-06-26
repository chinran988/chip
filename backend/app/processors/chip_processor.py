"""ChipProcessor — 每日採集完成後，從 raw_ 表計算衍生指標寫入 processed_chip.

執行邏輯
--------
1. 以 target_date 為基準，抓近 STREAK_WINDOW 個交易日的 raw_institutional 資料。
2. 用 pandas 計算各股外資 / 投信連買連賣天數（streak）。
3. 抓 target_date 的 raw_margin 資料（含前一交易日做 change 計算）。
4. JOIN 後寫入 processed_chip（upsert）。

連買天數算法
-----------
對每支股票，依日期排序後：
  sign = sign(net)  → +1 / 0 / -1
  每次 sign 改變就重設計數器，連續相同方向則累加。
  streak = sign × count（正=連買，負=連賣，0=無資料）
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd
from sqlalchemy import text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.processed import ProcessedChip

logger = logging.getLogger("chip.processor")

STREAK_WINDOW = 60   # 往前取幾個交易日做 streak 計算
BATCH_SIZE    = 90   # upsert batch (ProcessedChip 有 14 欄)


# ── helpers ───────────────────────────────────────────────────────────────────

def _streak_series(net_series: pd.Series) -> pd.Series:
    """Give a time-ordered Series of net values, return streak per row."""
    sign = net_series.apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    # Cumulative group counter — increments every time sign changes
    grp = (sign != sign.shift(1)).cumsum()
    count = sign.groupby(grp).cumcount() + 1
    return sign * count


# ── main processor ────────────────────────────────────────────────────────────

class ChipProcessor:

    def __init__(self, db: Session):
        self.db = db

    def process(self, target_date: date) -> int:
        """Compute derived indicators for target_date.  Returns rows upserted."""
        logger.info("processing chip indicators for %s", target_date)

        # ── 1. Institutional data for streak window ──────────────────────
        window_start = target_date - timedelta(days=STREAK_WINDOW * 2)  # buffer for holidays
        inst_df = self._load_institutional(window_start, target_date)
        if inst_df.empty:
            logger.warning("no institutional data for %s", target_date)
            return 0

        # ── 2. Compute nets (T86 unit = 股, convert ÷1000 → 張) ─────────
        inst_df["foreign_net"] = (inst_df["foreign_buy"] - inst_df["foreign_sell"]) // 1000
        inst_df["trust_net"]   = (inst_df["trust_buy"]   - inst_df["trust_sell"])   // 1000
        inst_df["dealer_net"]  = (
            inst_df["dealer_buy"] + inst_df["dealer_hedge_buy"]
            - inst_df["dealer_sell"] - inst_df["dealer_hedge_sell"]
        ) // 1000
        inst_df["total_net"] = inst_df["foreign_net"] + inst_df["trust_net"] + inst_df["dealer_net"]

        # ── 3. Streak per stock ──────────────────────────────────────────
        inst_df = inst_df.sort_values(["stock_id", "date"])
        inst_df["foreign_streak"] = (
            inst_df.groupby("stock_id")["foreign_net"]
            .transform(_streak_series)
        )
        inst_df["trust_streak"] = (
            inst_df.groupby("stock_id")["trust_net"]
            .transform(_streak_series)
        )

        # Keep only target_date rows
        today_inst = inst_df[inst_df["date"] == pd.Timestamp(target_date)].copy()
        if today_inst.empty:
            logger.warning("no institutional rows on %s after filter", target_date)
            return 0

        # ── 4. Margin data ───────────────────────────────────────────────
        prev_date = self._prev_trading_date(target_date)
        margin_today = self._load_margin(target_date)
        margin_prev  = self._load_margin(prev_date) if prev_date else pd.DataFrame()

        if not margin_today.empty and not margin_prev.empty:
            margin_today = margin_today.merge(
                margin_prev[["stock_id", "margin_balance", "short_balance"]]
                .rename(columns={"margin_balance": "mb_prev", "short_balance": "sb_prev"}),
                on="stock_id", how="left"
            )
            margin_today["margin_change"] = margin_today["margin_balance"] - margin_today["mb_prev"].fillna(0)
            margin_today["short_change"]  = margin_today["short_balance"]  - margin_today["sb_prev"].fillna(0)
        elif not margin_today.empty:
            margin_today["margin_change"] = 0
            margin_today["short_change"]  = 0

        # ── 5. Merge inst + margin ───────────────────────────────────────
        cols_inst = ["stock_id", "foreign_net", "trust_net", "dealer_net", "total_net",
                     "foreign_streak", "trust_streak"]
        merged = today_inst[cols_inst].copy()

        if not margin_today.empty:
            cols_margin = ["stock_id", "margin_balance", "short_balance",
                           "margin_change", "short_change"]
            merged = merged.merge(margin_today[cols_margin], on="stock_id", how="left")
        else:
            merged["margin_balance"] = 0
            merged["margin_change"]  = 0
            merged["short_balance"]  = 0
            merged["short_change"]   = 0

        # Fill missing margin with 0
        for col in ["margin_balance", "short_balance", "margin_change", "short_change"]:
            merged[col] = merged[col].fillna(0).astype(int)

        # margin_ratio
        total_marg = merged["margin_balance"] + merged["short_balance"]
        merged["margin_ratio"] = merged.apply(
            lambda r: round(r["margin_balance"] / total_marg[r.name] * 100, 2)
            if total_marg[r.name] > 0 else None,
            axis=1,
        )

        merged["date"] = target_date

        # ── 6. Upsert ────────────────────────────────────────────────────
        rows = merged.to_dict("records")
        count = self._upsert(rows)
        self.db.commit()
        logger.info("processed_chip: upserted %d rows for %s", count, target_date)
        return count

    # ── DB helpers ────────────────────────────────────────────────────────────

    def _load_institutional(self, start: date, end: date) -> pd.DataFrame:
        sql = text("""
            SELECT date, stock_id,
                   foreign_buy, foreign_sell,
                   trust_buy, trust_sell,
                   dealer_buy, dealer_sell,
                   dealer_hedge_buy, dealer_hedge_sell
            FROM raw_institutional
            WHERE date BETWEEN :s AND :e
            ORDER BY stock_id, date
        """)
        rows = self.db.execute(sql, {"s": str(start), "e": str(end)}).fetchall()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows, columns=[
            "date", "stock_id",
            "foreign_buy", "foreign_sell",
            "trust_buy", "trust_sell",
            "dealer_buy", "dealer_sell",
            "dealer_hedge_buy", "dealer_hedge_sell",
        ])
        df["date"] = pd.to_datetime(df["date"])
        for c in df.columns[2:]:
            df[c] = df[c].fillna(0).astype(int)
        return df

    def _load_margin(self, target: date) -> pd.DataFrame:
        sql = text("""
            SELECT stock_id, margin_balance, short_balance
            FROM raw_margin
            WHERE date = :d
        """)
        rows = self.db.execute(sql, {"d": str(target)}).fetchall()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows, columns=["stock_id", "margin_balance", "short_balance"])
        df["margin_balance"] = df["margin_balance"].fillna(0).astype(int)
        df["short_balance"]  = df["short_balance"].fillna(0).astype(int)
        return df

    def _prev_trading_date(self, d: date) -> date | None:
        sql = text("""
            SELECT date FROM trading_calendar
            WHERE is_trading_day = 1 AND date < :d
            ORDER BY date DESC LIMIT 1
        """)
        row = self.db.execute(sql, {"d": str(d)}).fetchone()
        return row[0] if row else None

    def _upsert(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        conflict_cols = ["date", "stock_id"]
        total = 0
        for i in range(0, len(rows), BATCH_SIZE):
            chunk = rows[i: i + BATCH_SIZE]
            stmt = sqlite_insert(ProcessedChip).values(chunk)
            update_cols = {c: stmt.excluded[c] for c in chunk[0] if c not in conflict_cols}
            stmt = stmt.on_conflict_do_update(
                index_elements=conflict_cols, set_=update_cols
            )
            result = self.db.execute(stmt)
            total += result.rowcount
        return total
