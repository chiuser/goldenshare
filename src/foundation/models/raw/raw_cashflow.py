from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Index, Numeric, PrimaryKeyConstraint, String, desc, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.datasets.cashflow_contracts import CASHFLOW_DECIMAL_FIELDS
from src.foundation.datasets.financial_statement_contracts import FINANCIAL_STATEMENT_IDENTITY_FIELDS
from src.foundation.models.base import Base


class RawCashflow(Base):
    __tablename__ = "cashflow"
    __table_args__ = (
        PrimaryKeyConstraint(*FINANCIAL_STATEMENT_IDENTITY_FIELDS, name="pk_raw_tushare_cashflow"),
        Index("idx_raw_tushare_cashflow_ann_report_code", "ann_date", "report_type", "ts_code"),
        Index(
            "idx_raw_tushare_cashflow_serving_rank",
            "report_type",
            "ts_code",
            "end_date",
            desc("update_flag"),
            desc("f_ann_date"),
            desc("ann_date"),
        ),
        {"schema": "raw_tushare"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    ann_date: Mapped[date] = mapped_column(Date, nullable=False)
    f_ann_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    comp_type: Mapped[str] = mapped_column(String(8), nullable=False)
    report_type: Mapped[str] = mapped_column(String(8), nullable=False)
    end_type: Mapped[str] = mapped_column(String(8), nullable=False)

    locals().update(
        {field_name: mapped_column(Numeric(), nullable=True) for field_name in CASHFLOW_DECIMAL_FIELDS}
    )

    update_flag: Mapped[str] = mapped_column(String(8), nullable=False)
    source_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    api_name: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'cashflow_vip'")
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


__all__ = ["RawCashflow"]
