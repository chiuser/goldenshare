from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin


class EquityDividend(TimestampMixin, Base):
    __tablename__ = "equity_dividend"
    __table_args__ = (
        Index("idx_equity_dividend_ex_date", "ex_date"),
        Index("idx_equity_dividend_ann_date", "ann_date"),
        {"schema": "core"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    end_date: Mapped[date | None] = mapped_column(Date)
    ann_date: Mapped[date] = mapped_column(Date, primary_key=True)
    record_date: Mapped[date] = mapped_column(Date, primary_key=True)
    ex_date: Mapped[date] = mapped_column(Date, primary_key=True)
    pay_date: Mapped[date | None] = mapped_column(Date)
    div_listdate: Mapped[date | None] = mapped_column(Date)
    imp_ann_date: Mapped[date | None] = mapped_column(Date)
    base_date: Mapped[date | None] = mapped_column(Date)
    base_share: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    div_proc: Mapped[str | None] = mapped_column(String(32))
    stk_div: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    stk_bo_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    stk_co_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    cash_div: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    cash_div_tax: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
