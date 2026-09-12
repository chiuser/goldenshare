"""Persisted request identity and fenced attempts, design §§4.17, 4.23."""
from datetime import datetime
from uuid import UUID

from sqlalchemy import (BigInteger, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint,
                        Index, Integer, LargeBinary, Text, UniqueConstraint, Uuid, text)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class WriteScope(Base):
    __tablename__ = "wealth_ta_write_scope"
    __table_args__ = (
        ForeignKeyConstraint(["owner_id", "scope_key", "holder_request_id"],
            ["app.wealth_ta_write_request.owner_id", "app.wealth_ta_write_request.scope_key", "app.wealth_ta_write_request.request_id"],
            name="fk_ta_scope_holder", deferrable=True, initially="DEFERRED", ondelete="RESTRICT", use_alter=True),
        CheckConstraint("length(scope_key) > 0", name="scope_key"),
        {"schema": "app"},
    )
    owner_id: Mapped[int] = mapped_column(Integer, ForeignKey("app.app_user.id", ondelete="RESTRICT"), primary_key=True)
    scope_key: Mapped[str] = mapped_column(Text, primary_key=True)
    holder_request_id: Mapped[UUID | None] = mapped_column(Uuid)


class WriteRequest(Base):
    __tablename__ = "wealth_ta_write_request"
    __table_args__ = (
        UniqueConstraint("owner_id", "scope_key", "request_id", name="uq_ta_request_scope_identity"),
        ForeignKeyConstraint(["owner_id", "scope_key"], ["app.wealth_ta_write_scope.owner_id", "app.wealth_ta_write_scope.scope_key"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["owner_id", "request_id", "current_attempt_id"],
            ["app.wealth_ta_write_attempt.owner_id", "app.wealth_ta_write_attempt.request_id", "app.wealth_ta_write_attempt.attempt_id"],
            name="fk_ta_request_current_attempt", deferrable=True, initially="DEFERRED", use_alter=True, ondelete="RESTRICT"),
        ForeignKeyConstraint(["owner_id", "request_id", "candidate_id"],
            ["app.wealth_ta_validation_candidate.owner_id", "app.wealth_ta_validation_candidate.request_id", "app.wealth_ta_validation_candidate.candidate_id"],
            name="fk_ta_request_candidate", deferrable=True, initially="DEFERRED", use_alter=True, ondelete="RESTRICT"),
        CheckConstraint("state_version >= 0 AND input_schema_version > 0 AND octet_length(input_digest) = 32", name="identity"),
        CheckConstraint("(input_payload IS NOT NULL AND candidate_id IS NULL) OR (input_payload IS NULL AND candidate_id IS NOT NULL)", name="input_source"),
        CheckConstraint("CASE WHEN operation_type IN ('TRADE_CORRECT','TRADE_VOID','CASH_FLOW_CORRECT','CASH_FLOW_VOID') "
                        "THEN COALESCE(jsonb_typeof(target) = 'object' AND target ?& ARRAY['accountId','kind','recordId'] "
                        "AND target - ARRAY['accountId','kind','recordId'] = '{}'::jsonb "
                        "AND scope_key = 'ACCOUNT_LEDGER:' || (target->>'accountId') "
                        "AND (target->>'recordId') ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' "
                        "AND target->>'kind' = CASE WHEN operation_type LIKE 'TRADE_%' THEN 'TRADE' ELSE 'CASH_FLOW' END, false) "
                        "ELSE target IS NULL END", name="target"),
        {"schema": "app"},
    )
    owner_id: Mapped[int] = mapped_column(Integer, ForeignKey("app.app_user.id", ondelete="RESTRICT"), primary_key=True)
    request_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    scope_key: Mapped[str] = mapped_column(Text)
    operation_type: Mapped[str] = mapped_column(Text)
    input_schema_version: Mapped[int] = mapped_column(Integer)
    input_digest: Mapped[bytes] = mapped_column(LargeBinary)
    input_payload: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    target: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    candidate_id: Mapped[UUID | None] = mapped_column(Uuid)
    current_attempt_id: Mapped[UUID] = mapped_column(Uuid)
    state_version: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WriteAttempt(Base):
    __tablename__ = "wealth_ta_write_attempt"
    __table_args__ = (
        ForeignKeyConstraint(["owner_id", "request_id"], ["app.wealth_ta_write_request.owner_id", "app.wealth_ta_write_request.request_id"], ondelete="RESTRICT"),
        CheckConstraint("fence >= 1", name="fence"),
        CheckConstraint("(status = 'PROCESSING' AND receipt IS NULL AND rejection IS NULL AND finished_at IS NULL "
                        "AND executor_id IS NOT NULL AND lease_until IS NOT NULL) OR "
                        "(status = 'SAVED' AND receipt IS NOT NULL AND rejection IS NULL AND finished_at IS NOT NULL) OR "
                        "(status = 'NOT_SAVED' AND receipt IS NULL AND rejection IS NOT NULL AND finished_at IS NOT NULL)", name="status"),
        Index("uq_ta_attempt_processing", "owner_id", "request_id", unique=True, postgresql_where=text("status = 'PROCESSING'")),
        Index("uq_ta_attempt_saved", "owner_id", "request_id", unique=True, postgresql_where=text("status = 'SAVED'")),
        Index("idx_ta_attempt_expired", "lease_until", "owner_id", "request_id", "attempt_id", postgresql_where=text("status = 'PROCESSING'")),
        {"schema": "app"},
    )
    owner_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    attempt_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    status: Mapped[str] = mapped_column(Text)
    fence: Mapped[int] = mapped_column(BigInteger)
    executor_id: Mapped[str | None] = mapped_column(Text)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    basis: Mapped[dict] = mapped_column(JSONB)
    checkpoint_ref: Mapped[UUID | None] = mapped_column(Uuid)
    receipt: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    rejection: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ValidationCandidate(Base):
    __tablename__ = "wealth_ta_validation_candidate"
    __table_args__ = (
        UniqueConstraint("owner_id", "request_id", name="uq_ta_candidate_request"),
        UniqueConstraint("owner_id", "request_id", "candidate_id", name="uq_ta_candidate_identity"),
        ForeignKeyConstraint(["owner_id", "account_id"], ["app.wealth_ta_account.owner_id", "app.wealth_ta_account.account_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["owner_id", "request_id"], ["app.wealth_ta_write_request.owner_id", "app.wealth_ta_write_request.request_id"],
            name="fk_ta_candidate_request", deferrable=True, initially="DEFERRED", use_alter=True, ondelete="RESTRICT"),
        CheckConstraint("(purpose = 'PREVIEW' AND request_id IS NULL) OR (purpose = 'SAVE' AND request_id IS NOT NULL)", name="purpose"),
        CheckConstraint("input_schema_version > 0 AND octet_length(input_digest) = 32", name="input"),
        {"schema": "app"},
    )
    candidate_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_id: Mapped[int] = mapped_column(Integer, ForeignKey("app.app_user.id", ondelete="RESTRICT"))
    account_id: Mapped[UUID | None] = mapped_column(Uuid)
    purpose: Mapped[str] = mapped_column(Text)
    request_id: Mapped[UUID | None] = mapped_column(Uuid)
    input_schema_version: Mapped[int] = mapped_column(Integer)
    input_digest: Mapped[bytes] = mapped_column(LargeBinary)
    input_payload: Mapped[dict] = mapped_column(JSONB)
    basis: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ValidationCheckpoint(Base):
    __tablename__ = "wealth_ta_validation_checkpoint"
    __table_args__ = (
        UniqueConstraint("candidate_id", "validation_run_id", "stage", "stock_key", "page_key", name="uq_ta_validation_page"),
        CheckConstraint("checked_row_count >= 0 AND octet_length(basis_digest) = 32", name="progress"),
        {"schema": "app"},
    )
    checkpoint_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    candidate_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("app.wealth_ta_validation_candidate.candidate_id", ondelete="RESTRICT"))
    validation_run_id: Mapped[UUID] = mapped_column(Uuid)
    attempt_id: Mapped[UUID | None] = mapped_column(Uuid)
    stage: Mapped[str] = mapped_column(Text)
    stock_key: Mapped[str] = mapped_column(Text)
    page_key: Mapped[str] = mapped_column(Text)
    basis_digest: Mapped[bytes] = mapped_column(LargeBinary)
    cursor: Mapped[dict] = mapped_column(JSONB)
    accumulator: Mapped[dict] = mapped_column(JSONB)
    completed_range: Mapped[dict] = mapped_column(JSONB)
    checked_row_count: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
