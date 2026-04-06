from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class EtfIndex(TimestampMixin, Base):
    __tablename__ = "etf_index"
    __table_args__ = (
        Index("idx_etf_index_pub_date", "pub_date"),
        Index("idx_etf_index_base_date", "base_date"),
        {"schema": "core"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    indx_name: Mapped[str | None] = mapped_column(String(128))
    indx_csname: Mapped[str | None] = mapped_column(String(128))
    pub_party_name: Mapped[str | None] = mapped_column(String(128))
    pub_date: Mapped[date | None] = mapped_column(Date)
    base_date: Mapped[date | None] = mapped_column(Date)
    bp: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    adj_circle: Mapped[str | None] = mapped_column(String(64))
