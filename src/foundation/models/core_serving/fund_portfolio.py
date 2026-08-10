from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Numeric, PrimaryKeyConstraint, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class FundPortfolio(Base):
    __tablename__ = "fund_portfolio"
    __table_args__ = (
        PrimaryKeyConstraint("end_date", "ts_code", "ann_date", "symbol", name="pk_core_serving_fund_portfolio"),
        {"schema": "core_serving", "postgresql_partition_by": "HASH (end_date)"},
    )

    ts_code: Mapped[str] = mapped_column(Text, nullable=False)
    ann_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    mkv: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    stk_mkv_ratio: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    stk_float_ratio: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    source_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
