from __future__ import annotations

from sqlalchemy import Boolean, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class DatasetSourceStatus(TimestampMixin, Base):
    __tablename__ = "dataset_source_status"
    __table_args__ = (
        Index("idx_dataset_source_status_active", "is_active"),
        {"schema": "foundation"},
    )

    dataset_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_key: Mapped[str] = mapped_column(String(32), primary_key=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    reason: Mapped[str] = mapped_column(String(255), nullable=False, default="")
