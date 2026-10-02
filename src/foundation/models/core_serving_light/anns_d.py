from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class AnnsDLight(Base):
    __tablename__ = "anns_d"
    __table_args__ = {"schema": "core_serving_light"}

    row_key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    ann_date: Mapped[date | None] = mapped_column(Date)
    ts_code: Mapped[str | None] = mapped_column(String(32))
    name: Mapped[str | None] = mapped_column(String(128))
    title: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    rec_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
