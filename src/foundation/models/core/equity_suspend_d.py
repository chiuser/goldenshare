from __future__ import annotations

from datetime import date

from sqlalchemy import BigInteger, Date, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class EquitySuspendD(TimestampMixin, Base):
    __tablename__ = "equity_suspend_d"
    __table_args__ = (
        Index("uq_equity_suspend_d_row_key_hash", "row_key_hash", unique=True),
        Index("idx_equity_suspend_d_trade_date", "trade_date"),
        Index("idx_equity_suspend_d_ts_code_trade_date", "ts_code", "trade_date"),
        {"schema": "core_serving"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    row_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    suspend_timing: Mapped[str | None] = mapped_column(String(32))
    suspend_type: Mapped[str | None] = mapped_column(String(16))

