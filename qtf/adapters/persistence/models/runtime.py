from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from qtf.contracts.runtime import (
    ExperimentRunStatus,
    InputPreflightPhase,
    InputPreflightStatus,
    InputSourceKind,
    RemediationOwner,
    ValidationStatus,
)
from src.foundation.models.base import Base, TimestampMixin


class InputPreflight(TimestampMixin, Base):
    __tablename__ = "input_preflight"
    __table_args__ = (
        UniqueConstraint("preflight_key", name="uq_qtf_input_preflight_preflight_key"),
        UniqueConstraint("request_key", name="uq_qtf_input_preflight_request_key"),
        CheckConstraint(
            "phase in ('DRAFT_PREVIEW', 'RUN_PREFLIGHT')",
            name="qtf_input_preflight_phase_valid",
        ),
        CheckConstraint(
            "status in ('PASS', 'BLOCKED')",
            name="qtf_input_preflight_status_valid",
        ),
        CheckConstraint("source_kind = 'PROD'", name="qtf_input_preflight_source_prod"),
        CheckConstraint(
            "length(source_contract_hash) = 64 and source_contract_hash = lower(source_contract_hash)",
            name="qtf_input_preflight_source_hash_shape",
        ),
        CheckConstraint(
            "length(content_hash) = 64 and content_hash = lower(content_hash)",
            name="qtf_input_preflight_content_hash_shape",
        ),
        CheckConstraint(
            "requested_start_date <= requested_end_date",
            name="qtf_input_preflight_requested_range_valid",
        ),
        CheckConstraint(
            "(effective_start_date is null and effective_end_date is null) or "
            "(effective_start_date is not null and effective_end_date is not null "
            "and effective_start_date <= effective_end_date)",
            name="qtf_input_preflight_effective_range_valid",
        ),
        CheckConstraint(
            "universe_count >= 0 and group_count >= 0 and valid_group_day_count >= 0 "
            "and excluded_group_day_count >= 0",
            name="qtf_input_preflight_counts_non_negative",
        ),
        Index("idx_qtf_input_preflight_revision_phase", "revision_id", "phase"),
        {"schema": "qtf"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    preflight_key: Mapped[str] = mapped_column(String(96), nullable=False)
    request_key: Mapped[str] = mapped_column(String(96), nullable=False)
    revision_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("qtf.experiment_revision.id", ondelete="RESTRICT"),
        nullable=False,
    )
    draft_hash: Mapped[str | None] = mapped_column(String(64))
    phase: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    source_kind: Mapped[str] = mapped_column(
        String(16),
        default=InputSourceKind.PROD.value,
        server_default=InputSourceKind.PROD.value,
        nullable=False,
    )
    source_contract_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    requested_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    requested_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    effective_start_date: Mapped[date | None] = mapped_column(Date)
    effective_end_date: Mapped[date | None] = mapped_column(Date)
    dataset_evidence_json: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    universe_count: Mapped[int] = mapped_column(Integer, nullable=False)
    group_count: Mapped[int] = mapped_column(Integer, nullable=False)
    valid_group_day_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    excluded_group_day_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    plan_estimate_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class InputPreflightIssue(Base):
    __tablename__ = "input_preflight_issue"
    __table_args__ = (
        CheckConstraint(
            "remediation_owner in ('PROD', 'LAKE')",
            name="qtf_input_preflight_issue_owner_valid",
        ),
        CheckConstraint(
            "severity in ('ERROR', 'WARN')",
            name="qtf_input_preflight_issue_severity_valid",
        ),
        Index("idx_qtf_input_preflight_issue_preflight", "preflight_id", "id"),
        {"schema": "qtf"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    preflight_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("qtf.input_preflight.id", ondelete="CASCADE"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(96), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    dataset_key: Mapped[str] = mapped_column(String(96), nullable=False)
    trade_date: Mapped[date | None] = mapped_column(Date)
    field_name: Mapped[str | None] = mapped_column(String(96))
    object_key: Mapped[str | None] = mapped_column(String(160))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    remediation_owner: Mapped[str] = mapped_column(String(16), nullable=False)
    evidence_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)


class ExperimentRun(TimestampMixin, Base):
    __tablename__ = "experiment_run"
    __table_args__ = (
        UniqueConstraint("run_key", name="uq_qtf_experiment_run_run_key"),
        UniqueConstraint("request_key", name="uq_qtf_experiment_run_request_key"),
        UniqueConstraint("task_run_id", name="uq_qtf_experiment_run_task_run_id"),
        CheckConstraint(
            "status in ('PLANNED', 'QUEUED', 'EXECUTING', 'COMPLETED', 'FAILED', 'CANCELED', 'BLOCKED')",
            name="qtf_experiment_run_status_valid",
        ),
        CheckConstraint(
            "validation_status in ('PENDING', 'VALID', 'INVALID', 'INSUFFICIENT', 'BLOCKED')",
            name="qtf_experiment_run_validation_status_valid",
        ),
        CheckConstraint(
            "code_commit is null or (length(code_commit) = 40 and code_commit = lower(code_commit))",
            name="qtf_experiment_run_commit_shape",
        ),
        CheckConstraint(
            "source_content_hash is null or (length(source_content_hash) = 64 and source_content_hash = lower(source_content_hash))",
            name="qtf_experiment_run_source_hash_shape",
        ),
        CheckConstraint(
            "result_hash is null or (length(result_hash) = 64 and result_hash = lower(result_hash))",
            name="qtf_experiment_run_result_hash_shape",
        ),
        CheckConstraint(
            "completed_parameter_set_count >= 0",
            name="qtf_experiment_run_completed_count_non_negative",
        ),
        Index("idx_qtf_experiment_run_revision_created", "revision_id", "created_at"),
        Index("idx_qtf_experiment_run_status_created", "status", "created_at"),
        {"schema": "qtf"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    run_key: Mapped[str] = mapped_column(String(96), nullable=False)
    request_key: Mapped[str] = mapped_column(String(96), nullable=False)
    revision_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("qtf.experiment_revision.id", ondelete="RESTRICT"),
        nullable=False,
    )
    input_preflight_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("qtf.input_preflight.id", ondelete="RESTRICT"),
    )
    task_run_id: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(
        String(24),
        default=ExperimentRunStatus.PLANNED.value,
        server_default=ExperimentRunStatus.PLANNED.value,
        nullable=False,
    )
    validation_status: Mapped[str] = mapped_column(
        String(24),
        default=ValidationStatus.PENDING.value,
        server_default=ValidationStatus.PENDING.value,
        nullable=False,
    )
    code_commit: Mapped[str | None] = mapped_column(String(40))
    runtime_fingerprint_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    formula_version: Mapped[str] = mapped_column(String(96), nullable=False)
    source_content_hash: Mapped[str | None] = mapped_column(String(64))
    result_hash: Mapped[str | None] = mapped_column(String(64))
    completed_parameter_set_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    failure_code: Mapped[str | None] = mapped_column(String(96))
    failure_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
