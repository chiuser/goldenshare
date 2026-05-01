from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawMajorNews(Base):
    __tablename__ = "major_news"
    __table_args__ = (
        Index("uq_raw_tushare_major_news_row_key_hash", "row_key_hash", unique=True),
        Index("idx_raw_tushare_major_news_src_time", "src", "pub_time"),
        Index("idx_raw_tushare_major_news_time", "pub_time"),
        {"schema": "raw_tushare"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    src: Mapped[str] = mapped_column(String(64), nullable=False)
    pub_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    row_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'major_news'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
