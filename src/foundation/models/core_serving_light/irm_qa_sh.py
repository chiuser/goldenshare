from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class IrmQaShLight(Base):
    __tablename__ = "irm_qa_sh"
    __table_args__ = {"schema": "core_serving_light"}

    row_key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    ts_code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str | None] = mapped_column(String(128))
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    q: Mapped[str] = mapped_column(Text, nullable=False)
    a: Mapped[str] = mapped_column(Text, nullable=False)
    pub_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
