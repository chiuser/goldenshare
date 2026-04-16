from __future__ import annotations

from datetime import date

from sqlalchemy import Date, Float, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class EquityDailyBarLight(TimestampMixin, Base):
    __tablename__ = "equity_daily_bar_light"
    __table_args__ = (
        Index("idx_equity_daily_bar_light_trade_date", "trade_date"),
        Index("idx_equity_daily_bar_light_ts_code_trade_date_desc", "ts_code", "trade_date"),
        {"schema": "core_serving_light"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[float | None] = mapped_column(Float(53))
    high: Mapped[float | None] = mapped_column(Float(53))
    low: Mapped[float | None] = mapped_column(Float(53))
    close: Mapped[float | None] = mapped_column(Float(53))
    pre_close: Mapped[float | None] = mapped_column(Float(53))
    change_amount: Mapped[float | None] = mapped_column(Float(53))
    pct_chg: Mapped[float | None] = mapped_column(Float(53))
    vol: Mapped[float | None] = mapped_column(Float(53))
    amount: Mapped[float | None] = mapped_column(Float(53))
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="tushare", server_default="tushare")

