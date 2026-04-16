from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawSuspendD(Base):
    __tablename__ = "suspend_d"
    __table_args__ = (
        Index("uq_raw_tushare_suspend_d_row_key_hash", "row_key_hash", unique=True),
        Index("idx_raw_tushare_suspend_d_trade_date", "trade_date"),
        Index("idx_raw_tushare_suspend_d_ts_code_trade_date", "ts_code", "trade_date"),
        {"schema": "raw_tushare"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    row_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    suspend_timing: Mapped[str | None] = mapped_column(String(32))
    suspend_type: Mapped[str | None] = mapped_column(String(16))
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'suspend_d'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)

