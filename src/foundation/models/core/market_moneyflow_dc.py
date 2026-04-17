from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class MarketMoneyflowDc(TimestampMixin, Base):
    __tablename__ = "market_moneyflow_dc"
    __table_args__ = (
        Index("idx_market_moneyflow_dc_trade_date", "trade_date"),
        {"schema": "core_serving"},
    )

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    close_sh: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    pct_change_sh: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    close_sz: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    pct_change_sz: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    net_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    net_amount_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    buy_elg_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    buy_elg_amount_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    buy_lg_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    buy_lg_amount_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    buy_md_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    buy_md_amount_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    buy_sm_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    buy_sm_amount_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
