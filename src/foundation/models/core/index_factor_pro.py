from __future__ import annotations

from datetime import date

from sqlalchemy import Date, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.models.base import Base, TimestampMixin


IDX_FACTOR_PRO_FIELDS = get_dataset_definition("idx_factor_pro").source.source_fields


class IndexFactorPro(TimestampMixin, Base):
    """Read-only ORM mapping for the raw-backed serving view."""

    __tablename__ = "index_factor_pro"
    __table_args__ = {"schema": "core_serving"}

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)

    for _field in IDX_FACTOR_PRO_FIELDS:
        if _field in {"ts_code", "trade_date"}:
            continue
        locals()[_field] = mapped_column(Float(53))
    del _field

    source: Mapped[str] = mapped_column(String(32), nullable=False)
