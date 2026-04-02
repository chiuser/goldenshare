from __future__ import annotations

from datetime import date

from sqlalchemy import Date, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin


class KplConceptCons(TimestampMixin, Base):
    __tablename__ = "kpl_concept_cons"
    __table_args__ = (
        Index("idx_kpl_concept_cons_trade_date", "trade_date"),
        Index("idx_kpl_concept_cons_con_code_trade_date", "con_code", "trade_date"),
        {"schema": "core"},
    )

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    con_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(128))
    con_name: Mapped[str | None] = mapped_column(String(128))
    ts_name: Mapped[str | None] = mapped_column(String(128))
    desc: Mapped[str | None] = mapped_column(Text)
    hot_num: Mapped[int | None] = mapped_column(Integer)
    raw_payload: Mapped[str | None] = mapped_column(Text)
