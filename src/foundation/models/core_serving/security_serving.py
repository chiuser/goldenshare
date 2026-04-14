from __future__ import annotations

from datetime import date

from sqlalchemy import Date, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class Security(TimestampMixin, Base):
    __tablename__ = "security_serving"
    __table_args__ = (
        Index("idx_security_serving_name", "name"),
        Index("idx_security_serving_industry", "industry"),
        Index("idx_security_serving_list_status", "list_status"),
        {"schema": "core_serving"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    symbol: Mapped[str | None] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    area: Mapped[str | None] = mapped_column(String(64))
    industry: Mapped[str | None] = mapped_column(String(64))
    fullname: Mapped[str | None] = mapped_column(String(128))
    enname: Mapped[str | None] = mapped_column(String(128))
    cnspell: Mapped[str | None] = mapped_column(String(32))
    market: Mapped[str | None] = mapped_column(String(32))
    exchange: Mapped[str | None] = mapped_column(String(16))
    curr_type: Mapped[str | None] = mapped_column(String(16))
    list_status: Mapped[str | None] = mapped_column(String(8))
    list_date: Mapped[date | None] = mapped_column(Date)
    delist_date: Mapped[date | None] = mapped_column(Date)
    is_hs: Mapped[str | None] = mapped_column(String(8))
    act_name: Mapped[str | None] = mapped_column(String(128))
    act_ent_type: Mapped[str | None] = mapped_column(String(64))
    security_type: Mapped[str] = mapped_column(String(16), nullable=False, default="EQUITY", server_default="EQUITY")
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="tushare", server_default="tushare")
