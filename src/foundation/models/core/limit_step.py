from __future__ import annotations

from datetime import date

from sqlalchemy import Date, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class LimitStep(TimestampMixin, Base):
    __tablename__ = "limit_step"
    __table_args__ = (
        Index("idx_limit_step_trade_date", "trade_date"),
        Index("idx_limit_step_nums_trade_date", "nums", "trade_date"),
        {"schema": "core"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    nums: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(128))
    raw_payload: Mapped[str | None] = mapped_column(Text)
