from __future__ import annotations

from datetime import date

from sqlalchemy import Date, Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class IndicatorState(TimestampMixin, Base):
    __tablename__ = "indicator_state"
    __table_args__ = (
        Index("idx_indicator_state_trade_date", "last_trade_date"),
        {"schema": "core"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    adjustment: Mapped[str] = mapped_column(String(16), primary_key=True)
    indicator_name: Mapped[str] = mapped_column(String(32), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    state_json: Mapped[dict] = mapped_column(JSON, nullable=False)

