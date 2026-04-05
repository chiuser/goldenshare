from __future__ import annotations

from datetime import date

from sqlalchemy import BigInteger, Date, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class EquityHolderNumber(TimestampMixin, Base):
    __tablename__ = "equity_holder_number"
    __table_args__ = (
        Index("uq_equity_holder_number_row_key_hash", "row_key_hash", unique=True),
        Index("idx_equity_holder_number_event_key_hash", "event_key_hash"),
        Index("idx_equity_holder_number_end_date", "end_date"),
        {"schema": "core"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    row_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ts_code: Mapped[str] = mapped_column(String(16))
    ann_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    holder_num: Mapped[int | None] = mapped_column(BigInteger)
