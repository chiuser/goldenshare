from __future__ import annotations

from datetime import date

from sqlalchemy import BigInteger, Date, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin


class EquityHolderNumber(TimestampMixin, Base):
    __tablename__ = "equity_holder_number"
    __table_args__ = (
        Index("idx_equity_holder_number_end_date", "end_date"),
        {"schema": "core"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    ann_date: Mapped[date] = mapped_column(Date, primary_key=True)
    end_date: Mapped[date | None] = mapped_column(Date)
    holder_num: Mapped[int | None] = mapped_column(BigInteger)
