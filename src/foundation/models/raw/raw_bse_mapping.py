from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawBseMapping(Base):
    __tablename__ = "bse_mapping"
    __table_args__ = (
        Index("idx_raw_tushare_bse_mapping_n_code", "n_code"),
        {"schema": "raw_tushare"},
    )

    o_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    n_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(128))
    list_date: Mapped[date | None] = mapped_column(Date)
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'bse_mapping'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
