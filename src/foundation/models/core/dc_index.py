from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class DcIndex(TimestampMixin, Base):
    __tablename__ = "dc_index"
    __table_args__ = (
        Index("idx_dc_index_trade_date", "trade_date"),
        Index("idx_dc_index_idx_type_trade_date", "idx_type", "trade_date"),
        {"schema": "core"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    name: Mapped[str | None] = mapped_column(String(128))
    leading: Mapped[str | None] = mapped_column(String(128))
    leading_code: Mapped[str | None] = mapped_column(String(16))
    pct_change: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    leading_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    total_mv: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    turnover_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    up_num: Mapped[int | None] = mapped_column(Integer)
    down_num: Mapped[int | None] = mapped_column(Integer)
    idx_type: Mapped[str | None] = mapped_column(String(32))
    level: Mapped[str | None] = mapped_column(String(32))
