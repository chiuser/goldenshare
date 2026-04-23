from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base
from src.foundation.services.sync_v2.fields import STK_FACTOR_PRO_FIELDS


class RawStkFactorPro(Base):
    __tablename__ = "stk_factor_pro"
    __table_args__ = (
        Index("idx_raw_tushare_stk_factor_pro_trade_date", "trade_date"),
        Index("idx_raw_tushare_stk_factor_pro_ts_code_trade_date", "ts_code", "trade_date"),
        {"schema": "raw_tushare"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)

    for _field in STK_FACTOR_PRO_FIELDS:
        if _field in {"ts_code", "trade_date"}:
            continue
        locals()[_field] = mapped_column(Float(53))
    del _field

    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'stk_factor_pro'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
