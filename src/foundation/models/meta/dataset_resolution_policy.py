from __future__ import annotations

from sqlalchemy import Boolean, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class DatasetResolutionPolicy(TimestampMixin, Base):
    __tablename__ = "dataset_resolution_policy"
    __table_args__ = {"schema": "foundation"}

    dataset_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    primary_source_key: Mapped[str] = mapped_column(String(32), nullable=False)
    fallback_source_keys: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    field_rules_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
