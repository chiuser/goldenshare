from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin


class IndexWeight(TimestampMixin, Base):
    __tablename__ = "index_weight"
    __table_args__ = (
        Index("idx_index_weight_index_code_trade_date", "index_code", "trade_date"),
        Index("idx_index_weight_con_code_trade_date", "con_code", "trade_date"),
        {"schema": "core"},
    )

    index_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    con_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    weight: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
