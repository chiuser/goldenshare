from __future__ import annotations

from datetime import date

from sqlalchemy import Date, Float, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.models.base import Base, TimestampMixin


STK_FACTOR_PRO_FIELDS = get_dataset_definition("stk_factor_pro").source.source_fields


class EquityFactorPro(TimestampMixin, Base):
    __tablename__ = "equity_factor_pro"
    __table_args__ = (
        Index("idx_equity_factor_pro_trade_date", "trade_date"),
        Index("idx_equity_factor_pro_ts_code_trade_date", "ts_code", "trade_date"),
        {"schema": "core_serving"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)

    for _field in STK_FACTOR_PRO_FIELDS:
        if _field in {"ts_code", "trade_date"}:
            continue
        locals()[_field] = mapped_column(Float(53))
    del _field

    source: Mapped[str] = mapped_column(String(32), nullable=False, default="tushare", server_default="tushare")
