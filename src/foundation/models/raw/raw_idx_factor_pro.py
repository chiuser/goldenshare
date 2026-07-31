from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.models.base import Base


IDX_FACTOR_PRO_FIELDS = get_dataset_definition("idx_factor_pro").source.source_fields


class RawIdxFactorPro(Base):
    __tablename__ = "idx_factor_pro"
    __table_args__ = (
        Index("idx_raw_tushare_idx_factor_pro_trade_date", "trade_date"),
        {"schema": "raw_tushare"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)

    for _field in IDX_FACTOR_PRO_FIELDS:
        if _field in {"ts_code", "trade_date"}:
            continue
        locals()[_field] = mapped_column(Float(53))
    del _field

    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'idx_factor_pro'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
