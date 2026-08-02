from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawNews(Base):
    __tablename__ = "news"
    __table_args__ = (
        Index("idx_raw_tushare_news_src_time", "src", "news_time"),
        Index("idx_raw_tushare_news_time", "news_time"),
        {"schema": "raw_tushare"},
    )

    src: Mapped[str] = mapped_column(String(32), nullable=False)
    news_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    title: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str | None] = mapped_column(Text)
    channels: Mapped[str | None] = mapped_column(Text)
    score: Mapped[str | None] = mapped_column(Text)
    row_key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'news'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
