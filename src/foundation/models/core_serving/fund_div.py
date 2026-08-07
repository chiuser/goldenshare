from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Index, Numeric, String, Text, desc
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class FundDiv(Base):
    __tablename__ = "fund_div"
    __table_args__ = (
        Index("idx_fund_div_ann_date_ts_code", desc("ann_date"), "ts_code"),
        Index("idx_fund_div_ts_code_ann_date", "ts_code", desc("ann_date")),
        {"schema": "core_serving"},
    )

    source_entity_key: Mapped[str] = mapped_column(Text, primary_key=True)
    source_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    identity_basis: Mapped[str] = mapped_column(Text, nullable=False)
    ts_code: Mapped[str] = mapped_column(Text, nullable=False)
    ann_date: Mapped[date] = mapped_column(Date, nullable=False)
    imp_anndate: Mapped[date | None] = mapped_column(Date)
    base_date: Mapped[date | None] = mapped_column(Date)
    div_proc: Mapped[str | None] = mapped_column(Text)
    record_date: Mapped[date | None] = mapped_column(Date)
    ex_date: Mapped[date | None] = mapped_column(Date)
    pay_date: Mapped[date | None] = mapped_column(Date)
    earpay_date: Mapped[date | None] = mapped_column(Date)
    net_ex_date: Mapped[date | None] = mapped_column(Date)
    div_cash: Mapped[Decimal | None] = mapped_column(Numeric(30, 10))
    base_unit: Mapped[Decimal | None] = mapped_column(Numeric(30, 10))
    ear_distr: Mapped[Decimal | None] = mapped_column(Numeric(30, 10))
    ear_amount: Mapped[Decimal | None] = mapped_column(Numeric(30, 10))
    account_date: Mapped[date | None] = mapped_column(Date)
    base_year: Mapped[str | None] = mapped_column(Text)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
