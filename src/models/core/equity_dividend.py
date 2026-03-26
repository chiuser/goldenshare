from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import BigInteger, Date, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin


class EquityDividend(TimestampMixin, Base):
    __tablename__ = "equity_dividend"
    __table_args__ = (
        Index("uq_equity_dividend_row_key_hash", "row_key_hash", unique=True),
        Index("idx_equity_dividend_event_key_hash", "event_key_hash"),
        Index("idx_equity_dividend_ex_date", "ex_date"),
        Index("idx_equity_dividend_ann_date", "ann_date"),
        {"schema": "core"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    row_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ts_code: Mapped[str] = mapped_column(String(16))
    end_date: Mapped[date] = mapped_column(Date)
    ann_date: Mapped[date] = mapped_column(Date)
    div_proc: Mapped[str] = mapped_column(String(32))
    record_date: Mapped[date | None] = mapped_column(Date)
    ex_date: Mapped[date | None] = mapped_column(Date)
    pay_date: Mapped[date | None] = mapped_column(Date)
    div_listdate: Mapped[date | None] = mapped_column(Date)
    imp_ann_date: Mapped[date | None] = mapped_column(Date)
    base_date: Mapped[date | None] = mapped_column(Date)
    base_share: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    stk_div: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    stk_bo_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    stk_co_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    cash_div: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    cash_div_tax: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
