from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class RawBlockTrade(Base):
    __tablename__ = "block_trade"
    __table_args__ = {"schema": "raw"}

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    buyer: Mapped[str] = mapped_column(String(128), primary_key=True)
    seller: Mapped[str] = mapped_column(String(128), primary_key=True)
    price: Mapped[float] = mapped_column(Numeric(18, 4), primary_key=True)
    vol: Mapped[float] = mapped_column(Numeric(20, 4), primary_key=True)
    amount: Mapped[float | None] = mapped_column(Numeric(20, 4))
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'block_trade'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
