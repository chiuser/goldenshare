from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class FundCompanyCurrent(TimestampMixin, Base):
    __tablename__ = "fund_company_current"
    __table_args__ = (Index("idx_fund_company_current_source_entity_key", "source_entity_key"), {"schema": "core_serving"})

    source_entity_key: Mapped[str] = mapped_column(Text, primary_key=True)
    source_content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    identity_basis: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    shortname: Mapped[str | None] = mapped_column(Text)
    short_enname: Mapped[str | None] = mapped_column(Text)
    province: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    office: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(Text)
    chairman: Mapped[str | None] = mapped_column(Text)
    manager: Mapped[str | None] = mapped_column(Text)
    reg_capital: Mapped[Decimal | None] = mapped_column(Numeric(30, 10))
    setup_date: Mapped[str | None] = mapped_column(String(8))
    end_date: Mapped[str | None] = mapped_column(String(8))
    employees: Mapped[Decimal | None] = mapped_column(Numeric(30, 10))
    main_business: Mapped[str | None] = mapped_column(Text)
    org_code: Mapped[str | None] = mapped_column(Text)
    credit_code: Mapped[str | None] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
