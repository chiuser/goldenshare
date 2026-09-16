"""Retained minute evidence, resumable checks and unique rule results (§4.26)."""
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, Date, DateTime,
                        ForeignKeyConstraint, Index, Integer, Numeric, Text,
                        UniqueConstraint, Uuid)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base
from .accounts import exact_numeric, finite_numeric


def rule_fk():
    return ForeignKeyConstraint(["owner_user_id", "rule_id"],
        ["app.wealth_ta_rule.owner_user_id", "app.wealth_ta_rule.rule_id"], ondelete="RESTRICT")


def evidence_fk(column, table, target):
    return ForeignKeyConstraint(["owner_user_id", "rule_id", column],
        [f"app.wealth_ta_{table}.owner_user_id", f"app.wealth_ta_{table}.rule_id",
         f"app.wealth_ta_{table}.{target}"], ondelete="RESTRICT")


class RuleMarketBasis(Base):
    __tablename__ = "wealth_ta_rule_market_basis"
    __table_args__ = (
        rule_fk(), UniqueConstraint("owner_user_id", "rule_id", "market_basis_id"),
        CheckConstraint("price_basis = 'QFQ' AND volume_unit = 'SHARE'", name="units"),
        CheckConstraint("jsonb_typeof(material) = 'array' AND jsonb_typeof(session_evidence) = 'object'", name="material"),
        {"schema": "app"},
    )
    market_basis_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(Integer)
    rule_id: Mapped[UUID] = mapped_column(Uuid)
    stock_code: Mapped[str] = mapped_column(Text)
    trade_date: Mapped[date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(Text)
    source_version: Mapped[str] = mapped_column(Text)
    price_basis: Mapped[str] = mapped_column(Text)
    time_label_version: Mapped[str] = mapped_column(Text)
    volume_unit: Mapped[str] = mapped_column(Text)
    session_evidence: Mapped[dict] = mapped_column(JSONB)
    coverage: Mapped[dict] = mapped_column(JSONB)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    material: Mapped[list] = mapped_column(JSONB)


class RuleCheck(Base):
    __tablename__ = "wealth_ta_rule_check"
    __table_args__ = (
        evidence_fk("rule_version_id", "rule_version", "rule_version_id"),
        evidence_fk("market_basis_id", "rule_market_basis", "market_basis_id"),
        UniqueConstraint("rule_id", "check_no"),
        UniqueConstraint("owner_user_id", "rule_id", "check_id"),
        UniqueConstraint("check_id", "market_basis_id"),
        CheckConstraint("check_no >= 1 AND execution_fence >= 1 AND requested_from <= requested_through", name="range"),
        CheckConstraint("status IN ('PENDING','CHECKING','WAITING_DATA','FAILED','COMPLETED')", name="status"),
        CheckConstraint("(status = 'COMPLETED') = (completed_at IS NOT NULL)", name="completion"),
        CheckConstraint("checked_through_at IS NULL OR (checked_through_at > requested_from AND checked_through_at <= requested_through)", name="through"),
        CheckConstraint("jsonb_typeof(missing_ranges) = 'array'", name="missing"),
        {"schema": "app"},
    )
    check_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(Integer)
    rule_id: Mapped[UUID] = mapped_column(Uuid)
    rule_version_id: Mapped[UUID] = mapped_column(Uuid)
    check_no: Mapped[int] = mapped_column(BigInteger)
    trade_date: Mapped[date] = mapped_column(Date)
    requested_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    requested_through: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text)
    checked_through_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    missing_ranges: Mapped[list] = mapped_column(JSONB)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    market_basis_id: Mapped[UUID | None] = mapped_column(Uuid)
    evaluator_version: Mapped[str] = mapped_column(Text)
    execution_fence: Mapped[int] = mapped_column(BigInteger)


Index("idx_ta_rule_check_order", RuleCheck.rule_id, RuleCheck.check_no.desc())


class RuleCheckProgress(Base):
    __tablename__ = "wealth_ta_rule_check_progress"
    __table_args__ = (
        ForeignKeyConstraint(["check_id", "market_basis_id"],
            ["app.wealth_ta_rule_check.check_id", "app.wealth_ta_rule_check.market_basis_id"], ondelete="RESTRICT"),
        CheckConstraint("processed_rows >= 0", name="rows"),
        CheckConstraint("(price_satisfied IS NULL) = (first_match_price IS NULL) AND "
                        "(volume_satisfied IS NULL) = (first_match_cumulative_shares IS NULL)", name="values"),
        CheckConstraint("first_match_price IS NULL OR (first_match_price > 0 AND " +
                        finite_numeric("first_match_price", scale=None) + ")", name="price"),
        CheckConstraint("first_match_cumulative_shares IS NULL OR (" +
                        exact_numeric("first_match_cumulative_shares", scale=0) + ")", name="match_volume"),
        CheckConstraint("cumulative_volume_shares IS NULL OR (" + exact_numeric("cumulative_volume_shares", scale=0) + ")", name="volume"),
        CheckConstraint("(first_match_at IS NULL AND first_match_price IS NULL AND first_match_cumulative_shares IS NULL "
                        "AND price_satisfied IS NULL AND volume_satisfied IS NULL) OR "
                        "(first_match_at IS NOT NULL AND (price_satisfied IS TRUE OR volume_satisfied IS TRUE) "
                        "AND price_satisfied IS NOT FALSE AND volume_satisfied IS NOT FALSE)", name="match"),
        {"schema": "app"},
    )
    check_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    market_basis_id: Mapped[UUID] = mapped_column(Uuid)
    cursor: Mapped[dict] = mapped_column(JSONB)
    cumulative_volume_shares: Mapped[Decimal | None] = mapped_column(Numeric)
    last_checkpoint_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_match_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_match_price: Mapped[Decimal | None] = mapped_column(Numeric)
    first_match_cumulative_shares: Mapped[Decimal | None] = mapped_column(Numeric)
    price_satisfied: Mapped[bool | None] = mapped_column(Boolean)
    volume_satisfied: Mapped[bool | None] = mapped_column(Boolean)
    processed_rows: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RuleResult(Base):
    __tablename__ = "wealth_ta_rule_result"
    __table_args__ = (
        rule_fk(), evidence_fk("trigger_version_id", "rule_version", "rule_version_id"),
        UniqueConstraint("rule_id"), UniqueConstraint("owner_user_id", "result_id", name="uq_ta_rule_result_owner"),
        UniqueConstraint("owner_user_id", "rule_id", "result_id", name="uq_ta_rule_result_identity"),
        CheckConstraint("(triggered AND trigger_version_id IS NOT NULL AND first_match_at IS NOT NULL) OR "
                        "(NOT triggered AND trigger_version_id IS NULL AND first_match_at IS NULL)", name="trigger"),
        CheckConstraint("(price_satisfied IS NULL) = (actual_price IS NULL) AND "
                        "(volume_satisfied IS NULL) = (cumulative_volume_shares IS NULL)", name="values"),
        CheckConstraint("NOT triggered OR ((price_satisfied IS TRUE OR volume_satisfied IS TRUE) "
                        "AND price_satisfied IS NOT FALSE AND volume_satisfied IS NOT FALSE)", name="satisfied"),
        CheckConstraint("actual_price IS NULL OR (actual_price > 0 AND " +
                        finite_numeric("actual_price", scale=None) + ")", name="price"),
        CheckConstraint("cumulative_volume_shares IS NULL OR (" +
                        exact_numeric("cumulative_volume_shares", scale=0) + ")", name="volume"),
        {"schema": "app"},
    )
    result_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(Integer)
    rule_id: Mapped[UUID] = mapped_column(Uuid)
    triggered: Mapped[bool] = mapped_column(Boolean)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    trigger_version_id: Mapped[UUID | None] = mapped_column(Uuid)
    first_match_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_price: Mapped[Decimal | None] = mapped_column(Numeric)
    cumulative_volume_shares: Mapped[Decimal | None] = mapped_column(Numeric)
    price_satisfied: Mapped[bool | None] = mapped_column(Boolean)
    volume_satisfied: Mapped[bool | None] = mapped_column(Boolean)


class RuleResultCheck(Base):
    __tablename__ = "wealth_ta_rule_result_check"
    __table_args__ = (
        evidence_fk("result_id", "rule_result", "result_id"),
        evidence_fk("check_id", "rule_check", "check_id"), {"schema": "app"},
    )
    result_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    check_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(Integer)
    rule_id: Mapped[UUID] = mapped_column(Uuid)
