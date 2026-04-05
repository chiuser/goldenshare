from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawHolderNumber(Base):
    __tablename__ = "holdernumber"
    __table_args__ = (
        Index("uq_raw_holdernumber_row_key_hash", "row_key_hash", unique=True),
        {"schema": "raw"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    row_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ts_code: Mapped[str | None] = mapped_column(String(16))
    ann_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    holder_num: Mapped[int | None] = mapped_column(BigInteger)
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'stk_holdernumber'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
