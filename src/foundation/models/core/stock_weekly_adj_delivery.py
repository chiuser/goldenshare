"""Append-only business delivery records, separate from TaskRun observations."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Identity,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    SmallInteger,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base

_JSON = JSON().with_variant(JSONB(), "postgresql")


class StockWeeklyAdjDelivery(Base):
    __tablename__ = "stock_weekly_adj_delivery"
    __table_args__ = (
        UniqueConstraint(
            "batch_id", "record_kind", "unit_id", name="uq_weekly_adj_delivery_unit"
        ),
        CheckConstraint("contract_version = 1", name="weekly_adj_delivery_version"),
        CheckConstraint(
            "record_kind IN ('plan','unit','batch_closed','bootstrap_closed')",
            name="weekly_adj_delivery_kind",
        ),
        CheckConstraint(
            "outcome IN ('published','source_empty_preserved','partial_source_preserved','no_trading_week')",
            name="weekly_adj_delivery_outcome",
        ),
        CheckConstraint(
            "rows_received >= 0 AND rows_unique >= 0 AND rows_written >= 0 AND rows_preserved >= 0",
            name="weekly_adj_delivery_counts",
        ),
        CheckConstraint(
            "octet_length(payload::text) <= CASE WHEN record_kind = 'plan' THEN 1048576 ELSE 8388608 END",
            name="weekly_adj_delivery_payload_bytes",
        ).ddl_if(dialect="postgresql"),
        Index("idx_weekly_adj_delivery_kind_revision", "record_kind", "revision"),
        {"schema": "core"},
    )
    revision: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), Identity(), primary_key=True
    )
    contract_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    batch_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    unit_id: Mapped[str] = mapped_column(String(128), nullable=False)
    record_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    intent: Mapped[dict] = mapped_column(_JSON, nullable=False)
    unit_kind: Mapped[str | None] = mapped_column(String(24))
    cutoff_week: Mapped[date] = mapped_column(Date, nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    ts_code: Mapped[str | None] = mapped_column(String(16))
    factor_scan_start: Mapped[date | None] = mapped_column(Date)
    factor_scan_end: Mapped[date | None] = mapped_column(Date)
    factor_target: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict] = mapped_column(_JSON, nullable=False)
    rows_received: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rows_unique: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rows_written: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rows_preserved: Mapped[int] = mapped_column(BigInteger, nullable=False)
    basis_date: Mapped[date | None] = mapped_column(Date)
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_summary: Mapped[dict] = mapped_column(_JSON, nullable=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
