from __future__ import annotations

from sqlalchemy import Boolean, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class DatasetPipelineMode(TimestampMixin, Base):
    __tablename__ = "dataset_pipeline_mode"
    __table_args__ = (
        Index("idx_dataset_pipeline_mode_mode", "mode"),
        Index("idx_dataset_pipeline_mode_source_scope", "source_scope"),
        {"schema": "ops"},
    )

    dataset_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    source_scope: Mapped[str] = mapped_column(String(64), nullable=False, default="tushare")
    raw_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    std_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resolution_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    serving_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
