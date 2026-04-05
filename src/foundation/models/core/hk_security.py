from __future__ import annotations

from datetime import date

from sqlalchemy import Date, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class HkSecurity(TimestampMixin, Base):
    __tablename__ = "hk_security"
    __table_args__ = (
        Index("idx_hk_security_name", "name"),
        Index("idx_hk_security_market", "market"),
        Index("idx_hk_security_list_status", "list_status"),
        {"schema": "core"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(128))
    fullname: Mapped[str | None] = mapped_column(String(256))
    enname: Mapped[str | None] = mapped_column(String(256))
    cn_spell: Mapped[str | None] = mapped_column(String(64))
    market: Mapped[str | None] = mapped_column(String(32))
    list_status: Mapped[str | None] = mapped_column(String(8))
    list_date: Mapped[date | None] = mapped_column(Date)
    delist_date: Mapped[date | None] = mapped_column(Date)
    trade_unit: Mapped[int | None] = mapped_column(Integer)
    isin: Mapped[str | None] = mapped_column(String(32))
    curr_type: Mapped[str | None] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="tushare", server_default="tushare")
