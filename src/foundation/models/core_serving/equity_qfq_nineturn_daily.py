from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    SmallInteger,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class EquityQfqNineTurnDaily(Base):
    __tablename__ = "equity_qfq_nineturn_daily"
    __table_args__ = (
        CheckConstraint("up_count >= 0 AND down_count >= 0", name="counts_non_negative"),
        CheckConstraint("NOT (up_count > 0 AND down_count > 0)", name="single_direction"),
        CheckConstraint(
            "nine_up_turn IS NULL OR nine_up_turn = '+9'",
            name="up_signal_allowed",
        ),
        CheckConstraint(
            "nine_down_turn IS NULL OR nine_down_turn = '-9'",
            name="down_signal_allowed",
        ),
        CheckConstraint(
            "nine_up_turn IS NULL OR up_count >= 9",
            name="up_signal_count",
        ),
        CheckConstraint(
            "nine_down_turn IS NULL OR down_count >= 9",
            name="down_signal_count",
        ),
        CheckConstraint(
            "NOT (nine_up_turn IS NOT NULL AND nine_down_turn IS NOT NULL)",
            name="single_signal",
        ),
        CheckConstraint("formula_version = 1", name="formula_version"),
        Index("idx_equity_qfq_nineturn_daily_trade_code", "trade_date", "ts_code"),
        {"schema": "core_serving"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    up_count: Mapped[int] = mapped_column(Integer, nullable=False)
    down_count: Mapped[int] = mapped_column(Integer, nullable=False)
    nine_up_turn: Mapped[str | None] = mapped_column(String(2))
    nine_down_turn: Mapped[str | None] = mapped_column(String(2))
    formula_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
