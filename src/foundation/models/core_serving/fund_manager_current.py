from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class FundManagerCurrent(TimestampMixin, Base):
    __tablename__ = "fund_manager_current"
    __table_args__ = (
        Index(
            "uq_fund_manager_current_source_entity_key",
            "source_entity_key",
            unique=True,
        ),
        Index("idx_fund_manager_current_ts_code", "ts_code"),
        Index(
            "idx_fund_manager_current_manager_identity_key",
            "manager_identity_key",
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
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
