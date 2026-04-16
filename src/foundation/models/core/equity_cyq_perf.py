from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class EquityCyqPerf(TimestampMixin, Base):
    __tablename__ = "equity_cyq_perf"
    __table_args__ = (
        Index("idx_equity_cyq_perf_trade_date", "trade_date"),
        Index("idx_equity_cyq_perf_ts_code_trade_date", "ts_code", "trade_date"),
        {"schema": "core_serving"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    his_low: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    his_high: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    cost_5pct: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    cost_15pct: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    cost_50pct: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    cost_85pct: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    cost_95pct: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    weight_avg: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    winner_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
