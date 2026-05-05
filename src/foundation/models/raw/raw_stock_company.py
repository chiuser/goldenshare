from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawStockCompany(Base):
    __tablename__ = "stock_company"
    __table_args__ = (
        Index("idx_raw_tushare_stock_company_exchange", "exchange"),
        Index("idx_raw_tushare_stock_company_com_id", "com_id"),
        {"schema": "raw_tushare"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    com_name: Mapped[str | None] = mapped_column(String(256))
    com_id: Mapped[str | None] = mapped_column(String(32))
    exchange: Mapped[str] = mapped_column(String(8), nullable=False)
    chairman: Mapped[str | None] = mapped_column(String(128))
    manager: Mapped[str | None] = mapped_column(String(128))
    secretary: Mapped[str | None] = mapped_column(String(128))
    reg_capital: Mapped[float | None] = mapped_column(Float)
    setup_date: Mapped[date | None] = mapped_column(Date)
    province: Mapped[str | None] = mapped_column(String(64))
    city: Mapped[str | None] = mapped_column(String(64))
    introduction: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(String(256))
    email: Mapped[str | None] = mapped_column(String(256))
    office: Mapped[str | None] = mapped_column(Text)
    employees: Mapped[int | None] = mapped_column(Integer)
    main_business: Mapped[str | None] = mapped_column(Text)
    business_scope: Mapped[str | None] = mapped_column(Text)
    ann_date: Mapped[date | None] = mapped_column(Date)
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'stock_company'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
