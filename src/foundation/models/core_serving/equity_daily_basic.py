from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class EquityDailyBasic(TimestampMixin, Base):
    __tablename__ = "equity_daily_basic"
    __table_args__ = (
        Index("idx_equity_daily_basic_trade_date", "trade_date"),
        Index("idx_equity_daily_basic_pb_trade_date", "trade_date", "pb"),
        Index("idx_equity_daily_basic_total_mv_trade_date", "trade_date", "total_mv"),
        {"schema": "core_serving"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    close: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    turnover_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    turnover_rate_f: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    volume_ratio: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    pe: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    pe_ttm: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    pb: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    ps: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    ps_ttm: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    dv_ratio: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    dv_ttm: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    total_share: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    float_share: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    free_share: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    total_mv: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    circ_mv: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
