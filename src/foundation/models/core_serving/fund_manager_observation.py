from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, desc, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class FundManagerObservation(TimestampMixin, Base):
    __tablename__ = "fund_manager_observation"
    __table_args__ = (
        Index(
            "idx_fund_manager_observation_entity_last_observed",
            "source_entity_key",
            desc("last_observed_at"),
        ),
        Index(
            "idx_fund_manager_observation_ts_code_last_observed",
            "ts_code",
            desc("last_observed_at"),
        ),
        Index(
            "idx_fund_manager_observation_manager_last_observed",
            "manager_identity_key",
            desc("last_observed_at"),
            postgresql_where=text("manager_identity_key IS NOT NULL"),
        ),
        {"schema": "core_serving"},
    )

    source_entity_key: Mapped[str] = mapped_column(Text, primary_key=True)
    source_content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    identity_basis: Mapped[str] = mapped_column(String(32), nullable=False)
    manager_identity_key: Mapped[str | None] = mapped_column(Text)
    ts_code: Mapped[str] = mapped_column(Text, nullable=False)
    ann_date: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    gender: Mapped[str | None] = mapped_column(Text)
    birth_year: Mapped[str | None] = mapped_column(Text)
    edu: Mapped[str | None] = mapped_column(Text)
    nationality: Mapped[str | None] = mapped_column(Text)
    begin_date: Mapped[str | None] = mapped_column(Text)
    end_date: Mapped[str | None] = mapped_column(Text)
    resume: Mapped[str | None] = mapped_column(Text)
    first_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
