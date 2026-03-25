from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class RawDividend(Base):
    __tablename__ = "dividend"
    __table_args__ = {"schema": "raw"}

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    end_date: Mapped[date | None] = mapped_column(Date)
    ann_date: Mapped[date | None] = mapped_column(Date, primary_key=True)
    record_date: Mapped[date | None] = mapped_column(Date, primary_key=True)
    ex_date: Mapped[date | None] = mapped_column(Date, primary_key=True)
    pay_date: Mapped[date | None] = mapped_column(Date)
    div_listdate: Mapped[date | None] = mapped_column(Date)
    imp_ann_date: Mapped[date | None] = mapped_column(Date)
    base_date: Mapped[date | None] = mapped_column(Date)
    base_share: Mapped[float | None] = mapped_column(Numeric(20, 4))
    div_proc: Mapped[str | None] = mapped_column(String(32))
    stk_div: Mapped[float | None] = mapped_column(Numeric(12, 6))
    stk_bo_rate: Mapped[float | None] = mapped_column(Numeric(12, 6))
    stk_co_rate: Mapped[float | None] = mapped_column(Numeric(12, 6))
    cash_div: Mapped[float | None] = mapped_column(Numeric(12, 6))
    cash_div_tax: Mapped[float | None] = mapped_column(Numeric(12, 6))
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'dividend'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
