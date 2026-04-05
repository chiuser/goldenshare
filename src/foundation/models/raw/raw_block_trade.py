from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Integer, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawBlockTrade(Base):
    __tablename__ = "block_trade"
    __table_args__ = {"schema": "raw"}

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16))
    trade_date: Mapped[date] = mapped_column(Date)
    buyer: Mapped[str | None] = mapped_column(String(128))
    seller: Mapped[str | None] = mapped_column(String(128))
    price: Mapped[float] = mapped_column(Numeric(18, 4))
    vol: Mapped[float] = mapped_column(Numeric(20, 4))
    amount: Mapped[float | None] = mapped_column(Numeric(20, 4))
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'block_trade'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
