"""Robot display metadata and durable test dispatch, no secret backfill."""
from alembic import op
import sqlalchemy as sa

revision = "20260916_000179"
down_revision = "20260916_000178"
branch_labels = depends_on = None


def upgrade():
    for table in ("wealth_ta_robot_candidate", "wealth_ta_robot_config"):
        op.add_column(table, sa.Column("has_signing_secret", sa.Boolean(), nullable=True), schema="app")
    op.add_column("wealth_ta_robot_candidate", sa.Column("request_digest", sa.Text(), nullable=True), schema="app")
    op.add_column("wealth_ta_robot", sa.Column("next_send_not_before", sa.DateTime(timezone=True), nullable=True), schema="app")
    op.add_column("wealth_ta_robot_test", sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True), schema="app")
    op.add_column("wealth_ta_robot_test", sa.Column("dispatch_token", sa.Uuid(), nullable=True), schema="app")
    op.create_check_constraint("ck_ta_robot_test_dispatch", "wealth_ta_robot_test",
        "(dispatched_at IS NULL) = (dispatch_token IS NULL)", schema="app")
    op.create_index("idx_ta_robot_test_pending", "wealth_ta_robot_test", ["started_at", "test_id"],
        postgresql_where=sa.text("state = 'IN_FLIGHT' AND dispatched_at IS NULL"), schema="app")
    op.create_index("idx_ta_robot_test_stale", "wealth_ta_robot_test", ["dispatched_at", "test_id"],
        postgresql_where=sa.text("state = 'IN_FLIGHT' AND dispatched_at IS NOT NULL"), schema="app")


def downgrade():
    raise RuntimeError("Robot evidence cannot be destructively downgraded")
