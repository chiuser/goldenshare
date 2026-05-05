from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawSt(Base):
    __tablename__ = "st"
    __table_args__ = (
        Index("uq_raw_tushare_st_row_key_hash", "row_key_hash", unique=True),
        Index("idx_raw_tushare_st_ts_code", "ts_code"),
        Index("idx_raw_tushare_st_pub_date", "pub_date"),
        Index("idx_raw_tushare_st_imp_date", "imp_date"),
        {"schema": "raw_tushare"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    row_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str | None] = mapped_column(String(128))
    pub_date: Mapped[date] = mapped_column(Date, nullable=False)
    imp_date: Mapped[date | None] = mapped_column(Date)
    st_tpye: Mapped[str] = mapped_column(String(64), nullable=False)
    st_reason: Mapped[str | None] = mapped_column(Text)
    st_explain: Mapped[str | None] = mapped_column(Text)
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'st'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
