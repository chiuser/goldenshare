from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class RawHolderNumber(Base):
    __tablename__ = "holdernumber"
    __table_args__ = {"schema": "raw"}

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    ann_date: Mapped[date] = mapped_column(Date, primary_key=True)
    end_date: Mapped[date | None] = mapped_column(Date)
    holder_num: Mapped[int | None] = mapped_column(BigInteger)
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'stk_holdernumber'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
