"""Frozen notification attempt evidence, following the verified head 179."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260916_000180"
down_revision = "20260916_000179"
branch_labels = depends_on = None


def upgrade():
    op.create_table("wealth_ta_notification_attempt",
        sa.Column("attempt_id", sa.Uuid(), primary_key=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("notification_id", sa.Uuid(), nullable=False),
        sa.Column("robot_id", sa.Uuid(), nullable=False),
        sa.Column("config_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_no", sa.BigInteger(), nullable=False),
        sa.Column("dispatch_token", sa.Uuid(), nullable=False),
        sa.Column("business_content", sa.Text(), nullable=False),
        sa.Column("content_digest", sa.Text(), nullable=False),
        sa.Column("template_version", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text()), sa.Column("response_code", sa.Integer()),
        sa.Column("result_history", JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id", "notification_id"],
            ["app.wealth_ta_notification.owner_user_id", "app.wealth_ta_notification.notification_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_user_id", "robot_id", "config_id"],
            ["app.wealth_ta_robot_config.owner_user_id", "app.wealth_ta_robot_config.robot_id", "app.wealth_ta_robot_config.config_id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("notification_id", "attempt_no", name="uq_ta_notification_attempt_no"),
        sa.UniqueConstraint("owner_user_id", "notification_id", "attempt_id", name="uq_ta_notification_attempt_identity"),
        sa.CheckConstraint("attempt_no >= 1 AND template_version = 'V1'", name="ck_ta_notification_attempt_version"),
        sa.CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name="ck_ta_notification_attempt_digest"),
        sa.CheckConstraint("(outcome = 'IN_FLIGHT' AND completed_at IS NULL AND reason IS NULL) OR "
            "(outcome IN ('SUCCEEDED','FAILED','UNKNOWN') AND completed_at IS NOT NULL AND completed_at >= started_at)", name="ck_ta_notification_attempt_outcome"),
        schema="app")
    op.create_index("uq_ta_notification_inflight", "wealth_ta_notification_attempt", ["notification_id"], unique=True,
        postgresql_where=sa.text("outcome = 'IN_FLIGHT'"), schema="app")
    op.create_index("idx_ta_notification_stale", "wealth_ta_notification_attempt", ["started_at", "attempt_id"],
        postgresql_where=sa.text("outcome = 'IN_FLIGHT'"), schema="app")
    op.create_index("idx_ta_notification_pending", "wealth_ta_notification", ["created_at", "notification_id"],
        postgresql_where=sa.text("state = 'PENDING'"), schema="app")
    op.create_foreign_key("fk_ta_notification_latest_attempt", "wealth_ta_notification", "wealth_ta_notification_attempt",
        ["owner_user_id", "notification_id", "latest_attempt_id"], ["owner_user_id", "notification_id", "attempt_id"],
        source_schema="app", referent_schema="app", deferrable=True, initially="DEFERRED", ondelete="RESTRICT")


def downgrade():
    raise RuntimeError("Notification evidence cannot be destructively downgraded")
