from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, desc
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class MktIdxBmkObservation(TimestampMixin, Base):
    __tablename__ = "mkt_idx_bmk_observation"
    __table_args__ = (
        Index("idx_mkt_idx_bmk_observation_entity_last_observed", "source_entity_key", desc("last_observed_at")),
        {"schema": "core_serving"},
    )

    source_entity_key: Mapped[str] = mapped_column(Text, primary_key=True)
    source_content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    identity_basis: Mapped[str] = mapped_column(String(32), nullable=False)
    ts_code: Mapped[str | None] = mapped_column(Text)
    symbol: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)
    fullname: Mapped[str | None] = mapped_column(Text)
    bmk_level: Mapped[str | None] = mapped_column(Text)
    bmk_type: Mapped[str | None] = mapped_column(Text)
    bmk_src: Mapped[str | None] = mapped_column(Text)
    idx_type: Mapped[str | None] = mapped_column(Text)
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
