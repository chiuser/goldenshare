from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class RawKplConceptCons(Base):
    __tablename__ = "kpl_concept_cons"
    __table_args__ = {"schema": "raw"}

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    con_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(128))
    con_name: Mapped[str | None] = mapped_column(String(128))
    ts_name: Mapped[str | None] = mapped_column(String(128))
    desc: Mapped[str | None] = mapped_column(Text)
    hot_num: Mapped[int | None] = mapped_column(Integer)
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'kpl_concept_cons'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
