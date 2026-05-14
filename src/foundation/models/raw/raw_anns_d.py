from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawAnnsD(Base):
    __tablename__ = "anns_d"
    __table_args__ = (
        Index("uq_raw_tushare_anns_d_row_key_hash", "row_key_hash", unique=True),
        Index("idx_raw_tushare_anns_d_ann_date", "ann_date"),
        Index("idx_raw_tushare_anns_d_ts_code_date", "ts_code", "ann_date"),
        Index("idx_raw_tushare_anns_d_rec_time", "rec_time"),
        {"schema": "raw_tushare"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ann_date: Mapped[date] = mapped_column(Date, nullable=False)
    ts_code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str | None] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    rec_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    row_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'anns_d'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
