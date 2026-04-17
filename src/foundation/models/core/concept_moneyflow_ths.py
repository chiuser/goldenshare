from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class ConceptMoneyflowThs(TimestampMixin, Base):
    __tablename__ = "concept_moneyflow_ths"
    __table_args__ = (
        Index("idx_concept_moneyflow_ths_trade_date", "trade_date"),
        Index("idx_concept_moneyflow_ths_ts_code_trade_date", "ts_code", "trade_date"),
        {"schema": "core_serving"},
    )

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(128))
    lead_stock: Mapped[str | None] = mapped_column(String(128))
    close_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    pct_change: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    industry_index: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    company_num: Mapped[int | None] = mapped_column(Integer)
    pct_change_stock: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    net_buy_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    net_sell_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    net_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
