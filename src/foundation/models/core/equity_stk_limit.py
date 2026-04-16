from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class EquityStkLimit(TimestampMixin, Base):
    __tablename__ = "equity_stk_limit"
    __table_args__ = (
        Index("idx_equity_stk_limit_trade_date", "trade_date"),
        {"schema": "core_serving"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    pre_close: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    up_limit: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    down_limit: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
