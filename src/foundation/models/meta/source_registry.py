from __future__ import annotations

from sqlalchemy import Boolean, Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class SourceRegistry(TimestampMixin, Base):
    __tablename__ = "source_registry"
    __table_args__ = (
        Index("idx_source_registry_enabled_priority", "enabled", "priority"),
        {"schema": "foundation"},
    )

    source_key: Mapped[str] = mapped_column(String(32), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    config_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
