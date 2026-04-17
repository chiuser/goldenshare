from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class EquityMoneyflowThs(TimestampMixin, Base):
    __tablename__ = "equity_moneyflow_ths"
    __table_args__ = (
        Index("idx_equity_moneyflow_ths_trade_date", "trade_date"),
        Index("idx_equity_moneyflow_ths_ts_code_trade_date", "ts_code", "trade_date"),
        {"schema": "core_serving"},
    )

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(64))
    pct_change: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    latest: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    net_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    net_d5_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    buy_lg_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    buy_lg_amount_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    buy_md_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    buy_md_amount_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    buy_sm_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    buy_sm_amount_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
