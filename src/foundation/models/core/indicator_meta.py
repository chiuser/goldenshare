from __future__ import annotations

from sqlalchemy import Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class IndicatorMeta(TimestampMixin, Base):
    __tablename__ = "indicator_meta"
    __table_args__ = (
        Index("idx_indicator_meta_indicator_updated", "indicator_name", "updated_at"),
        {"schema": "core"},
    )

    indicator_name: Mapped[str] = mapped_column(String(32), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    params_json: Mapped[dict] = mapped_column(JSON, nullable=False)

