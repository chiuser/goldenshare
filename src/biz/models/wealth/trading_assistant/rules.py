"""Private rule identities and immutable versions, design §4.26.

This module does not register routes, create tables, or authorize notifications.
Cross-version invariants require the command's rule-row lock as well as these
row-local constraints. Robot qualification remains an application-side check.
"""
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, Date, DateTime,
                        ForeignKey, ForeignKeyConstraint, Index, Integer,
                        Numeric, Text, UniqueConstraint, Uuid)
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base
from .accounts import exact_numeric


class RobotIdentity(Base):
    """Stable owner-bound target only; existence is not proof of qualification.

    M7 owns configuration, credential/test evidence and the configuration FK.
    There is no production writer or flag that can mark this identity verified.
    """
    __tablename__ = "wealth_ta_robot"
    __table_args__ = (
        UniqueConstraint("owner_user_id"),
        UniqueConstraint("owner_user_id", "robot_id", name="uq_ta_robot_identity"),
        ForeignKeyConstraint(["owner_user_id", "robot_id", "current_config_id"],
            ["app.wealth_ta_robot_config.owner_user_id", "app.wealth_ta_robot_config.robot_id",
             "app.wealth_ta_robot_config.config_id"], name="fk_ta_robot_current_config",
            use_alter=True, deferrable=True, initially="DEFERRED", ondelete="RESTRICT"),
        {"schema": "app"},
    )
    robot_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("app.app_user.id", ondelete="RESTRICT"))
    current_config_id: Mapped[UUID | None] = mapped_column(Uuid)
    next_send_not_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Rule(Base):
    __tablename__ = "wealth_ta_rule"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "rule_id"),
        ForeignKeyConstraint(["owner_user_id", "account_id"],
            ["app.wealth_ta_account.owner_id", "app.wealth_ta_account.account_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["owner_user_id", "rule_id", "current_version_id"],
            ["app.wealth_ta_rule_version.owner_user_id", "app.wealth_ta_rule_version.rule_id",
             "app.wealth_ta_rule_version.rule_version_id"], name="fk_ta_rule_current_version",
            deferrable=True, initially="DEFERRED", use_alter=True, ondelete="RESTRICT"),
        ForeignKeyConstraint(["owner_user_id", "rule_id", "result_id"],
            ["app.wealth_ta_rule_result.owner_user_id", "app.wealth_ta_rule_result.rule_id",
             "app.wealth_ta_rule_result.result_id"], name="fk_ta_rule_result",
            deferrable=True, initially="DEFERRED", use_alter=True, ondelete="RESTRICT"),
        CheckConstraint("(kind = 'PLAN' AND account_id IS NOT NULL) OR "
                        "(kind = 'ALERT' AND account_id IS NULL)", name="kind"),
        CheckConstraint("state_version >= 1 AND last_check_no >= 0", name="versions"),
        CheckConstraint("(state = 'ACTIVE' AND closed_at IS NULL AND ended_at IS NULL AND result_id IS NULL) OR "
                        "(state = 'CLOSED' AND closed_at IS NOT NULL AND ended_at IS NULL AND result_id IS NULL) OR "
                        "(state = 'ENDED' AND closed_at IS NULL AND ended_at IS NOT NULL AND result_id IS NOT NULL)", name="state"),
        {"schema": "app"},
    )
    rule_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("app.app_user.id", ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(Text)
    account_id: Mapped[UUID | None] = mapped_column(Uuid)
    current_version_id: Mapped[UUID] = mapped_column(Uuid)
    state: Mapped[str] = mapped_column(Text)
    state_version: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_id: Mapped[UUID | None] = mapped_column(Uuid)
    last_check_no: Mapped[int] = mapped_column(BigInteger)


Index("idx_ta_rule_owner_order", Rule.owner_user_id, Rule.kind, Rule.created_at.desc(), Rule.rule_id.desc())
Index("idx_ta_rule_account_order", Rule.owner_user_id, Rule.account_id, Rule.created_at.desc(), Rule.rule_id.desc())


class RuleVersion(Base):
    __tablename__ = "wealth_ta_rule_version"
    __table_args__ = (
        UniqueConstraint("rule_id", "version_no"),
        UniqueConstraint("owner_user_id", "rule_id", "rule_version_id"),
        ForeignKeyConstraint(["owner_user_id", "rule_id"],
            ["app.wealth_ta_rule.owner_user_id", "app.wealth_ta_rule.rule_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["owner_user_id", "robot_id"],
            ["app.wealth_ta_robot.owner_user_id", "app.wealth_ta_robot.robot_id"], ondelete="RESTRICT"),
        CheckConstraint("version_no >= 1 AND deadline_at > effective_at", name="version_time"),
        CheckConstraint("length(btrim(stock_code)) > 0 AND length(btrim(stock_name_at_save)) > 0", name="stock"),
        CheckConstraint("direction IS NULL OR direction IN ('BUY','SELL')", name="direction"),
        CheckConstraint("source IN ('TRADING_ASSISTANT','STOCK_DETAIL')", name="source"),
        CheckConstraint("(notify_enabled AND robot_id IS NOT NULL) OR (NOT notify_enabled AND robot_id IS NULL)", name="notification"),
        CheckConstraint("COALESCE((price_operator IS NULL AND price_lower IS NULL AND price_upper IS NULL) OR "
                        "(price_operator = 'LTE' AND price_lower IS NULL AND price_upper IS NOT NULL) OR "
                        "(price_operator = 'GTE' AND price_lower IS NOT NULL AND price_upper IS NULL) OR "
                        "(price_operator = 'BETWEEN' AND price_lower IS NOT NULL AND price_upper IS NOT NULL "
                        "AND price_lower <= price_upper), false)", name="price_branch"),
        CheckConstraint("COALESCE((volume_operator IS NULL AND volume_threshold_lots IS NULL) OR "
                        "(volume_operator IN ('LTE','GTE') AND volume_threshold_lots IS NOT NULL), false)", name="volume_branch"),
        CheckConstraint("price_operator IS NOT NULL OR volume_operator IS NOT NULL", name="enabled"),
        *(CheckConstraint(f"{name} IS NULL OR ({exact_numeric(name, positive=True)})", name=name)
          for name in ("price_lower", "price_upper", "volume_threshold_lots")),
        {"schema": "app"},
    )
    rule_version_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(Integer)
    rule_id: Mapped[UUID] = mapped_column(Uuid)
    version_no: Mapped[int] = mapped_column(BigInteger)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    stock_code: Mapped[str] = mapped_column(Text)
    stock_name_at_save: Mapped[str] = mapped_column(Text)
    direction: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    price_operator: Mapped[str | None] = mapped_column(Text)
    price_lower: Mapped[Decimal | None] = mapped_column(Numeric)
    price_upper: Mapped[Decimal | None] = mapped_column(Numeric)
    volume_operator: Mapped[str | None] = mapped_column(Text)
    volume_threshold_lots: Mapped[Decimal | None] = mapped_column(Numeric)
    notify_enabled: Mapped[bool] = mapped_column(Boolean)
    robot_id: Mapped[UUID | None] = mapped_column(Uuid)


class RuleExecution(Base):
    __tablename__ = "wealth_ta_rule_execution"
    __table_args__ = (
        ForeignKeyConstraint(["owner_user_id", "rule_id"],
            ["app.wealth_ta_rule.owner_user_id", "app.wealth_ta_rule.rule_id"], ondelete="RESTRICT"),
        CheckConstraint("fence >= 0 AND observed_state_version >= 1 AND transient_failures >= 0", name="versions"),
        CheckConstraint("(executor_id IS NULL AND lease_until IS NULL) OR "
                        "(executor_id IS NOT NULL AND length(executor_id) > 0 AND lease_until IS NOT NULL AND fence >= 1)", name="lease"),
        Index("idx_ta_rule_execution_due", "next_attempt_at", "rule_id"),
        {"schema": "app"},
    )
    rule_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(Integer)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    executor_id: Mapped[str | None] = mapped_column(Text)
    fence: Mapped[int] = mapped_column(BigInteger)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_state_version: Mapped[int] = mapped_column(BigInteger)
    next_trade_date: Mapped[date | None] = mapped_column(Date)
    last_business_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    transient_failures: Mapped[int] = mapped_column(Integer)
    waiting_reason: Mapped[str | None] = mapped_column(Text)
