"""Processed / derived indicator tables."""
from __future__ import annotations

from sqlalchemy import Date, Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ProcessedChip(Base):
    """Per-stock daily chip summary derived from raw_institutional + raw_margin.

    Columns
    -------
    foreign_net / trust_net / dealer_net
        Net buy volume in lots (張).  dealer includes both self-trading and hedge.
    total_net
        Sum of foreign + trust + dealer net.
    foreign_streak / trust_streak
        Consecutive-direction count.
        +N = N consecutive buying days ending on this date.
        -N = N consecutive selling days.
        0  = no trade / data gap.
    margin_balance / short_balance
        Margin-loan / short-sell outstanding balance in lots.
    margin_change / short_change
        Day-over-day change in balance (today − yesterday).
    margin_ratio
        margin_balance / (margin_balance + short_balance) × 100.
        NULL when both are zero.
    """

    __tablename__ = "processed_chip"
    __table_args__ = (
        UniqueConstraint("date", "stock_id", name="uq_processed_chip_date_stock"),
        Index("ix_processed_chip_date", "date"),
        Index("ix_processed_chip_stock", "stock_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[str] = mapped_column(Date, nullable=False)
    stock_id: Mapped[str] = mapped_column(String(10), nullable=False)

    # ── Three institutions ──────────────────────────────────────────────────
    foreign_net: Mapped[int] = mapped_column(Integer, default=0)
    trust_net: Mapped[int] = mapped_column(Integer, default=0)
    dealer_net: Mapped[int] = mapped_column(Integer, default=0)
    total_net: Mapped[int] = mapped_column(Integer, default=0)

    # ── Consecutive streaks ─────────────────────────────────────────────────
    foreign_streak: Mapped[int] = mapped_column(Integer, default=0)
    trust_streak: Mapped[int] = mapped_column(Integer, default=0)

    # ── Margin / short ──────────────────────────────────────────────────────
    margin_balance: Mapped[int] = mapped_column(Integer, default=0)
    short_balance: Mapped[int] = mapped_column(Integer, default=0)
    margin_change: Mapped[int] = mapped_column(Integer, default=0)
    short_change: Mapped[int] = mapped_column(Integer, default=0)
    margin_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
