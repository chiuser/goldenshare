from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class RealtimeRuntimeConfigRecord(TimestampMixin, Base):
    __tablename__ = "realtime_runtime_config"
    __table_args__ = {"schema": "foundation"}

    object_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    object_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    runtime_config_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    requires_collector_restart: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_by_user_id: Mapped[int | None] = mapped_column(BigInteger)
