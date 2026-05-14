from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawIrmQaSh(Base):
    __tablename__ = "irm_qa_sh"
    __table_args__ = (
        Index("uq_raw_tushare_irm_qa_sh_row_key_hash", "row_key_hash", unique=True),
        Index("idx_raw_tushare_irm_qa_sh_trade_date", "trade_date"),
        Index("idx_raw_tushare_irm_qa_sh_ts_code_date", "ts_code", "trade_date"),
        Index("idx_raw_tushare_irm_qa_sh_pub_time", "pub_time"),
        {"schema": "raw_tushare"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str | None] = mapped_column(String(128))
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    q: Mapped[str] = mapped_column(Text, nullable=False)
    a: Mapped[str] = mapped_column(Text, nullable=False)
    pub_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    row_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'irm_qa_sh'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
