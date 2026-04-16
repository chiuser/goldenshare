from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Index, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawCyqPerf(Base):
    __tablename__ = "cyq_perf"
    __table_args__ = (
        Index("idx_raw_tushare_cyq_perf_trade_date", "trade_date"),
        Index("idx_raw_tushare_cyq_perf_ts_code_trade_date", "ts_code", "trade_date"),
        {"schema": "raw_tushare"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    his_low: Mapped[float | None] = mapped_column(Numeric(18, 4))
    his_high: Mapped[float | None] = mapped_column(Numeric(18, 4))
    cost_5pct: Mapped[float | None] = mapped_column(Numeric(18, 4))
    cost_15pct: Mapped[float | None] = mapped_column(Numeric(18, 4))
    cost_50pct: Mapped[float | None] = mapped_column(Numeric(18, 4))
    cost_85pct: Mapped[float | None] = mapped_column(Numeric(18, 4))
    cost_95pct: Mapped[float | None] = mapped_column(Numeric(18, 4))
    weight_avg: Mapped[float | None] = mapped_column(Numeric(18, 4))
    winner_rate: Mapped[float | None] = mapped_column(Numeric(10, 4))
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'cyq_perf'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
