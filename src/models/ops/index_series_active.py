from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin


class IndexSeriesActive(TimestampMixin, Base):
    __tablename__ = "index_series_active"
    __table_args__ = (
        Index("idx_index_series_active_resource", "resource"),
        Index("idx_index_series_active_resource_last_seen", "resource", "last_seen_date"),
        {"schema": "ops"},
    )

    resource: Mapped[str] = mapped_column(String(64), primary_key=True)
    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    first_seen_date: Mapped[date] = mapped_column(Date, nullable=False)
    last_seen_date: Mapped[date] = mapped_column(Date, nullable=False)
    last_checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
