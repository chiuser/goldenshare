from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Numeric, String, desc
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class EquityMarginDetail(TimestampMixin, Base):
    __tablename__ = "equity_margin_detail"
    __table_args__ = (
        Index("idx_equity_margin_detail_trade_date", "trade_date"),
        Index("idx_equity_margin_detail_ts_code_trade_date_desc", "ts_code", desc("trade_date")),
        {"schema": "core_serving"},
    )

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(64))
    rzye: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    rqye: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    rzmre: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    rqyl: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    rzche: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    rqchl: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    rqmcl: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    rzrqye: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
