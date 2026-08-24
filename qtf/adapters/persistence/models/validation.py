from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from qtf.contracts.validation import (
    ParameterEffectStatus,
    RunConclusionKind,
    SignalEntryType,
    ValidationGateResultStatus,
)
from src.foundation.models.base import Base, TimestampMixin


_HASH_CHECK = "length({column}) = 64 and {column} = lower({column})"


class RunGateResult(TimestampMixin, Base):
    __tablename__ = "run_gate_result"
    __table_args__ = (
        UniqueConstraint("run_id", "gate_key", name="uq_qtf_run_gate_result_run_gate"),
        CheckConstraint(
            "gate_key in ('INPUT', 'TIME_FRONTIER', 'FUTURE_LEAKAGE', 'WARMUP', "
            "'COVERAGE', 'OUT_OF_SAMPLE_SENSITIVITY')",
            name="qtf_run_gate_result_gate_valid",
        ),
        CheckConstraint(
            "status in ('PASS', 'FAIL', 'INSUFFICIENT')",
            name="qtf_run_gate_result_status_valid",
        ),
        Index("idx_qtf_run_gate_result_run", "run_id", "gate_key"),
        {"schema": "qtf"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("qtf.experiment_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    gate_key: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        default=ValidationGateResultStatus.INSUFFICIENT.value,
        nullable=False,
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RunParameterResult(TimestampMixin, Base):
    __tablename__ = "run_parameter_result"
    __table_args__ = (
        UniqueConstraint("result_key", name="uq_qtf_run_parameter_result_result_key"),
        UniqueConstraint(
            "run_id",
            "parameter_set_key",
            name="uq_qtf_run_parameter_result_run_parameter",
        ),
        CheckConstraint(
            "effect_status in ('SUPPORTED', 'REJECTED', 'INSUFFICIENT')",
            name="qtf_run_parameter_result_effect_status_valid",
        ),
        CheckConstraint(
            _HASH_CHECK.format(column="result_hash"),
            name="qtf_run_parameter_result_hash_shape",
        ),
        Index("idx_qtf_run_parameter_result_run_status", "run_id", "effect_status"),
        {"schema": "qtf"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    result_key: Mapped[str] = mapped_column(String(96), nullable=False)
    run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("qtf.experiment_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    parameter_set_key: Mapped[str] = mapped_column(String(96), nullable=False)
    parameter_values_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    entry_metrics_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    retention_metrics_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    baseline_metrics_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    lift_metrics_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    coverage_metrics_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    sample_metrics_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    confidence_intervals_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    metrics_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    effect_status: Mapped[str] = mapped_column(
        String(24),
        default=ParameterEffectStatus.INSUFFICIENT.value,
        nullable=False,
    )
    result_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class SectorSignalEvent(TimestampMixin, Base):
    __tablename__ = "sector_signal_event"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "parameter_set_key",
            "signal_trade_date",
            "sector_code",
            "entry_type",
            name="uq_qtf_sector_signal_event_identity",
        ),
        CheckConstraint("sector_level = 2", name="qtf_sector_signal_event_level_two"),
        CheckConstraint(
            "entry_type in ('ENTRY', 'RETENTION')",
            name="qtf_sector_signal_event_entry_type_valid",
        ),
        CheckConstraint(
            "signal_rank_pct >= 0 and signal_rank_pct <= 100",
            name="qtf_sector_signal_event_rank_valid",
        ),
        CheckConstraint(
            _HASH_CHECK.format(column="event_hash"),
            name="qtf_sector_signal_event_hash_shape",
        ),
        Index(
            "idx_qtf_sector_signal_event_run_date",
            "run_id",
            "signal_trade_date",
            "sector_code",
        ),
        {"schema": "qtf"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("qtf.experiment_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    parameter_set_key: Mapped[str] = mapped_column(String(96), nullable=False)
    signal_trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    sector_code: Mapped[str] = mapped_column(String(32), nullable=False)
    parent_sector_code: Mapped[str] = mapped_column(String(32), nullable=False)
    sector_level: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_type: Mapped[str] = mapped_column(
        String(16),
        default=SignalEntryType.ENTRY.value,
        nullable=False,
    )
    signal_state_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    signal_rank_pct: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    future_outcomes_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    input_completeness_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class RunConclusion(TimestampMixin, Base):
    __tablename__ = "run_conclusion"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_qtf_run_conclusion_run"),
        UniqueConstraint("request_key", name="uq_qtf_run_conclusion_request_key"),
        CheckConstraint(
            "conclusion in ('ENDED', 'OBSERVED')",
            name="qtf_run_conclusion_kind_valid",
        ),
        Index("idx_qtf_run_conclusion_concluded", "concluded_at"),
        {"schema": "qtf"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("qtf.experiment_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    request_key: Mapped[str] = mapped_column(String(96), nullable=False)
    conclusion: Mapped[str] = mapped_column(
        String(16),
        default=RunConclusionKind.OBSERVED.value,
        nullable=False,
    )
    actor_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    concluded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
