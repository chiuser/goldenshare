from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    event,
    inspect,
)
from sqlalchemy.orm import Mapped, mapped_column

from qtf.contracts.errors import QtfStateConflict
from qtf.contracts.research import ExperimentRevisionStatus, ResearchStatus
from src.foundation.models.base import Base, TimestampMixin


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class Research(TimestampMixin, Base):
    __tablename__ = "research"
    __table_args__ = (
        UniqueConstraint("research_key", name="uq_qtf_research_research_key"),
        UniqueConstraint("create_request_key", name="uq_qtf_research_create_request_key"),
        CheckConstraint(
            "status in ('DRAFT', 'ACTIVE', 'ENDED')",
            name="qtf_research_status_valid",
        ),
        CheckConstraint("latest_revision_no >= 1", name="qtf_research_latest_revision_positive"),
        {"schema": "qtf"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    research_key: Mapped[str] = mapped_column(String(96), nullable=False)
    create_request_key: Mapped[str] = mapped_column(String(96), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    template_key: Mapped[str] = mapped_column(String(96), nullable=False)
    capability_key: Mapped[str] = mapped_column(String(96), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24),
        default=ResearchStatus.DRAFT.value,
        server_default=ResearchStatus.DRAFT.value,
        nullable=False,
    )
    latest_revision_no: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    created_by_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)


Index("idx_qtf_research_status_updated_at", Research.status, Research.updated_at.desc())


class ExperimentRevision(TimestampMixin, Base):
    __tablename__ = "experiment_revision"
    __table_args__ = (
        UniqueConstraint("revision_key", name="uq_qtf_experiment_revision_revision_key"),
        UniqueConstraint("request_key", name="uq_qtf_experiment_revision_request_key"),
        UniqueConstraint(
            "research_id",
            "revision_no",
            name="uq_qtf_experiment_revision_research_revision_no",
        ),
        UniqueConstraint("revision_hash", name="uq_qtf_experiment_revision_revision_hash"),
        CheckConstraint(
            "status in ('DRAFT', 'FROZEN', 'RETIRED')",
            name="qtf_experiment_revision_status_valid",
        ),
        CheckConstraint("revision_no >= 1", name="qtf_experiment_revision_revision_no_positive"),
        CheckConstraint("draft_version >= 1", name="qtf_experiment_revision_draft_version_positive"),
        CheckConstraint(
            "revision_hash is null or (length(revision_hash) = 64 and revision_hash = lower(revision_hash))",
            name="qtf_experiment_revision_hash_shape",
        ),
        CheckConstraint(
            "(status = 'FROZEN' and revision_hash is not null and frozen_by_user_id is not null and frozen_at is not null) "
            "or (status in ('DRAFT', 'RETIRED') and revision_hash is null "
            "and frozen_by_user_id is null and frozen_at is null)",
            name="qtf_experiment_revision_frozen_fields_consistent",
        ),
        Index("idx_qtf_experiment_revision_research_status", "research_id", "status"),
        {"schema": "qtf"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    revision_key: Mapped[str] = mapped_column(String(96), nullable=False)
    request_key: Mapped[str] = mapped_column(String(96), nullable=False)
    research_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("qtf.research.id", ondelete="RESTRICT"),
        nullable=False,
    )
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_revision_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("qtf.experiment_revision.id", ondelete="RESTRICT"),
    )
    status: Mapped[str] = mapped_column(
        String(24),
        default=ExperimentRevisionStatus.DRAFT.value,
        server_default=ExperimentRevisionStatus.DRAFT.value,
        nullable=False,
    )
    problem_statement: Mapped[str] = mapped_column(Text, nullable=False)
    success_definition_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    non_goals_json: Mapped[list[object]] = mapped_column(JSON, nullable=False)
    source_contract_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    universe_spec_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    comparison_spec_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    formula_key: Mapped[str] = mapped_column(String(96), nullable=False)
    formula_version: Mapped[str] = mapped_column(String(96), nullable=False)
    parameter_schema_key: Mapped[str] = mapped_column(String(96), nullable=False)
    parameter_schema_version: Mapped[str] = mapped_column(String(96), nullable=False)
    effective_params_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    validation_spec_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    budget_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    draft_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    revision_hash: Mapped[str | None] = mapped_column(String(64))
    frozen_by_user_id: Mapped[int | None] = mapped_column(BigInteger)
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


_IMMUTABLE_AFTER_FROZEN = (
    "revision_key",
    "request_key",
    "research_id",
    "revision_no",
    "parent_revision_id",
    "status",
    "problem_statement",
    "success_definition_json",
    "non_goals_json",
    "source_contract_json",
    "universe_spec_json",
    "comparison_spec_json",
    "formula_key",
    "formula_version",
    "parameter_schema_key",
    "parameter_schema_version",
    "effective_params_json",
    "validation_spec_json",
    "budget_json",
    "draft_version",
    "revision_hash",
    "frozen_by_user_id",
    "frozen_at",
)


def _validate_revision_shape(target: ExperimentRevision) -> None:
    if target.revision_hash is not None and not _SHA256_PATTERN.fullmatch(target.revision_hash):
        raise QtfStateConflict("revision_hash must be a lowercase SHA-256 hex digest")
    if target.status == ExperimentRevisionStatus.FROZEN.value:
        if target.revision_hash is None or target.frozen_by_user_id is None or target.frozen_at is None:
            raise QtfStateConflict("FROZEN revision requires hash, actor and timestamp")
    elif target.revision_hash is not None or target.frozen_by_user_id is not None or target.frozen_at is not None:
        raise QtfStateConflict("only FROZEN revisions may contain frozen hash and audit fields")


@event.listens_for(ExperimentRevision, "before_insert")
def _validate_revision_insert(_mapper: object, _connection: object, target: ExperimentRevision) -> None:
    _validate_revision_shape(target)


@event.listens_for(ExperimentRevision, "before_update")
def _protect_revision_state(_mapper: object, _connection: object, target: ExperimentRevision) -> None:
    state = inspect(target)
    status_history = state.attrs.status.history
    previous_status = status_history.deleted[0] if status_history.deleted else target.status

    if previous_status == ExperimentRevisionStatus.FROZEN.value:
        changed = [field for field in _IMMUTABLE_AFTER_FROZEN if state.attrs[field].history.has_changes()]
        if changed:
            raise QtfStateConflict(f"FROZEN revision is immutable: {', '.join(changed)}")
    elif previous_status == ExperimentRevisionStatus.RETIRED.value:
        changed = [field for field in _IMMUTABLE_AFTER_FROZEN if state.attrs[field].history.has_changes()]
        if changed:
            raise QtfStateConflict(f"RETIRED revision is immutable: {', '.join(changed)}")
    elif target.status not in {
        ExperimentRevisionStatus.DRAFT.value,
        ExperimentRevisionStatus.FROZEN.value,
        ExperimentRevisionStatus.RETIRED.value,
    }:
        raise QtfStateConflict(f"unsupported revision status transition: {previous_status} -> {target.status}")

    _validate_revision_shape(target)
