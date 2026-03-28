from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin


class EtfBasic(TimestampMixin, Base):
    __tablename__ = "etf_basic"
    __table_args__ = (
        Index("idx_etf_basic_list_status", "list_status"),
        Index("idx_etf_basic_exchange", "exchange"),
        Index("idx_etf_basic_index_code", "index_code"),
        Index("idx_etf_basic_mgr_name", "mgr_name"),
        {"schema": "core"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    csname: Mapped[str | None] = mapped_column(String(64))
    extname: Mapped[str | None] = mapped_column(String(128))
    cname: Mapped[str | None] = mapped_column(String(256))
    index_code: Mapped[str | None] = mapped_column(String(16))
    index_name: Mapped[str | None] = mapped_column(String(128))
    setup_date: Mapped[date | None] = mapped_column(Date)
    list_date: Mapped[date | None] = mapped_column(Date)
    list_status: Mapped[str | None] = mapped_column(String(8))
    exchange: Mapped[str | None] = mapped_column(String(16))
    mgr_name: Mapped[str | None] = mapped_column(String(64))
    custod_name: Mapped[str | None] = mapped_column(String(64))
    mgt_fee: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    etf_type: Mapped[str | None] = mapped_column(String(32))
