from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import CHAR, CheckConstraint, Date, DateTime, ForeignKeyConstraint, Index, JSON, String, UniqueConstraint, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")
SHA256_SQL = "^[0-9a-f]{64}$"


class WealthSectorAnalysisPublishBatch(Base):
    __tablename__ = "wealth_sector_analysis_publish_batch"
    __table_args__ = (
        CheckConstraint(
            "status IN ('BUILDING', 'PUBLISHED', 'SUPERSEDED', 'FAILED')",
            name="wealth_sector_analysis_batch_status_allowed",
        ),
        CheckConstraint(
            f"source_hash ~ '{SHA256_SQL}' AND plan_hash ~ '{SHA256_SQL}' "
            f"AND content_hash ~ '{SHA256_SQL}'",
            name="wealth_sector_analysis_batch_hashes_sha256",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "previous_batch_id IS NULL OR previous_trade_date IS NOT NULL",
            name="wealth_sector_analysis_previous_binding_complete",
        ),
        ForeignKeyConstraint(
            ("previous_batch_id", "previous_trade_date"),
            (
                "core_serving.wealth_sector_analysis_publish_batch.batch_id",
                "core_serving.wealth_sector_analysis_publish_batch.trade_date",
            ),
            name="fk_wealth_sector_analysis_previous_batch_date",
        ),
        UniqueConstraint(
            "batch_id",
            "trade_date",
            name="uq_wealth_sector_analysis_batch_id_trade_date",
        ),
        Index(
            "uq_wealth_sector_analysis_one_published_per_date",
            "trade_date",
            unique=True,
            postgresql_where=text("status = 'PUBLISHED'"),
            sqlite_where=text("status = 'PUBLISHED'"),
        ),
        Index(
            "uq_wealth_sector_analysis_success_content",
            "trade_date",
            "plan_hash",
            "content_hash",
            unique=True,
            postgresql_where=text("status IN ('PUBLISHED', 'SUPERSEDED')"),
            sqlite_where=text("status IN ('PUBLISHED', 'SUPERSEDED')"),
        ),
        Index(
            "idx_wealth_sector_analysis_batch_status_trade_published",
            "status",
            "trade_date",
            "published_at",
        ),
        Index(
            "idx_wealth_sector_analysis_batch_hierarchy_trade",
            "hierarchy_version",
            "trade_date",
        ),
        {"schema": "core_serving"},
    )

    batch_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    previous_trade_date: Mapped[date | None] = mapped_column(Date)
    previous_batch_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    hierarchy_version: Mapped[str] = mapped_column(String(128), nullable=False)
    formula_bundle_version: Mapped[str] = mapped_column(String(64), nullable=False)
    template_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    plan_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    content_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    source_dates_json: Mapped[dict[str, object]] = mapped_column(JSON_DOCUMENT, nullable=False)
    source_row_counts_json: Mapped[dict[str, object]] = mapped_column(JSON_DOCUMENT, nullable=False)
    expected_fact_counts_json: Mapped[dict[str, object]] = mapped_column(JSON_DOCUMENT, nullable=False)
    actual_fact_counts_json: Mapped[dict[str, object]] = mapped_column(JSON_DOCUMENT, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason_code: Mapped[str | None] = mapped_column(String(64))
