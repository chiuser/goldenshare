from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawLimitCptList(Base):
    __tablename__ = "limit_cpt_list"
    __table_args__ = {"schema": "raw"}

    ts_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    name: Mapped[str | None] = mapped_column(String(128))
    days: Mapped[int | None] = mapped_column(Integer)
    up_stat: Mapped[str | None] = mapped_column(String(64))
    cons_nums: Mapped[int | None] = mapped_column(Integer)
    up_nums: Mapped[int | None] = mapped_column(Integer)
    pct_chg: Mapped[float | None] = mapped_column(Numeric(10, 4))
    rank: Mapped[str | None] = mapped_column(String(32))
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'limit_cpt_list'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
