from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class NamechangeLight(Base):
    __tablename__ = "namechange"
    __table_args__ = {"schema": "core_serving_light"}

    row_key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    ann_date: Mapped[date | None] = mapped_column(Date)
    change_reason: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
