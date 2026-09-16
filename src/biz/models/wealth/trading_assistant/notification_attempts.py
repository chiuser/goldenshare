"""Immutable send identity/content and bounded terminal evidence."""
from datetime import datetime
from uuid import UUID
from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKeyConstraint, Index, Integer, Text, UniqueConstraint, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from src.foundation.models.base import Base


class NotificationAttempt(Base):
    __tablename__ = "wealth_ta_notification_attempt"
    __table_args__ = (
        ForeignKeyConstraint(["owner_user_id", "notification_id"],
            ["app.wealth_ta_notification.owner_user_id", "app.wealth_ta_notification.notification_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["owner_user_id", "robot_id", "config_id"],
            ["app.wealth_ta_robot_config.owner_user_id", "app.wealth_ta_robot_config.robot_id", "app.wealth_ta_robot_config.config_id"], ondelete="RESTRICT"),
        UniqueConstraint("notification_id", "attempt_no", name="uq_ta_notification_attempt_no"),
        UniqueConstraint("owner_user_id", "notification_id", "attempt_id", name="uq_ta_notification_attempt_identity"),
        CheckConstraint("attempt_no >= 1 AND template_version = 'V1'", name="version"),
        CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="digest"),
        CheckConstraint("(outcome = 'IN_FLIGHT' AND completed_at IS NULL AND reason IS NULL) OR "
            "(outcome IN ('SUCCEEDED','FAILED','UNKNOWN') AND completed_at IS NOT NULL AND completed_at >= started_at)", name="outcome"),
        {"schema": "app"},
    )
    attempt_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(Integer)
    notification_id: Mapped[UUID] = mapped_column(Uuid)
    robot_id: Mapped[UUID] = mapped_column(Uuid)
    config_id: Mapped[UUID] = mapped_column(Uuid)
    attempt_no: Mapped[int] = mapped_column(BigInteger)
    dispatch_token: Mapped[UUID] = mapped_column(Uuid)
    business_content: Mapped[str] = mapped_column(Text)
    content_digest: Mapped[str] = mapped_column(Text)
    template_version: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    response_code: Mapped[int | None] = mapped_column(Integer)
    result_history: Mapped[list] = mapped_column(JSONB)


Index("uq_ta_notification_inflight", NotificationAttempt.notification_id, unique=True,
    postgresql_where=text("outcome = 'IN_FLIGHT'"))
Index("idx_ta_notification_stale", NotificationAttempt.started_at, NotificationAttempt.attempt_id,
    postgresql_where=text("outcome = 'IN_FLIGHT'"))
