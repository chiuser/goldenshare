from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class MajorNewsLight(Base):
    __tablename__ = "major_news"
    __table_args__ = {"schema": "core_serving_light"}

    row_key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    src: Mapped[str] = mapped_column(String(64), nullable=False)
    pub_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
