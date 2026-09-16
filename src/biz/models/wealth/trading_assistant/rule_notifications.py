"""One trigger notification intent; credential and network attempts belong to M7."""
from datetime import datetime
from uuid import UUID
from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKeyConstraint, Index, Integer, Text, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column
from src.foundation.models.base import Base
from .rule_checks import evidence_fk


class TriggerNotification(Base):
    __tablename__ = "wealth_ta_notification"
    __table_args__ = (
        evidence_fk("trigger_id", "rule_result", "result_id"),
        evidence_fk("rule_version_id", "rule_version", "rule_version_id"),
        ForeignKeyConstraint(["owner_user_id", "robot_id"],
            ["app.wealth_ta_robot.owner_user_id", "app.wealth_ta_robot.robot_id"], ondelete="RESTRICT"),
        UniqueConstraint("owner_user_id", "trigger_id", "purpose", name="uq_ta_notification_trigger"),
        UniqueConstraint("owner_user_id", "notification_id", name="uq_ta_notification_owner"),
        ForeignKeyConstraint(["owner_user_id", "notification_id", "latest_attempt_id"],
            ["app.wealth_ta_notification_attempt.owner_user_id", "app.wealth_ta_notification_attempt.notification_id",
             "app.wealth_ta_notification_attempt.attempt_id"], name="fk_ta_notification_latest_attempt",
            use_alter=True, deferrable=True, initially="DEFERRED", ondelete="RESTRICT"),
        CheckConstraint("purpose = 'TRIGGER_NOTIFICATION'", name="purpose"),
        CheckConstraint("state IN ('PENDING','SENDING','SUCCEEDED','FAILED','UNKNOWN') AND state_version >= 1", name="state"),
        {"schema": "app"},
    )
    notification_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(Integer)
    rule_id: Mapped[UUID] = mapped_column(Uuid)
    trigger_id: Mapped[UUID] = mapped_column(Uuid)
    rule_version_id: Mapped[UUID] = mapped_column(Uuid)
    robot_id: Mapped[UUID] = mapped_column(Uuid)
    purpose: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(Text)
    state_version: Mapped[int] = mapped_column(BigInteger)
    latest_attempt_id: Mapped[UUID | None] = mapped_column(Uuid)
    accepted_retry_request_id: Mapped[UUID | None] = mapped_column(Uuid)


Index("idx_ta_notification_pending", TriggerNotification.created_at, TriggerNotification.notification_id,
    postgresql_where=text("state = 'PENDING'"))
