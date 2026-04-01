from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class RawThsMember(Base):
    __tablename__ = "ths_member"
    __table_args__ = {"schema": "raw"}

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    con_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    con_name: Mapped[str | None] = mapped_column(String(128))
    weight: Mapped[float | None] = mapped_column(Numeric(12, 6))
    in_date: Mapped[date | None] = mapped_column(Date)
    out_date: Mapped[date | None] = mapped_column(Date)
    is_new: Mapped[str | None] = mapped_column(String(8))
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'ths_member'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
