"""Retain account-scoped readiness progress before fixing a generation cutoff."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260912_000176"
down_revision = "20260912_000175"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("wealth_ta_cutoff_preparation",
        sa.Column("account_id", sa.Uuid(), primary_key=True),
        sa.Column("target_version", sa.BigInteger(), primary_key=True),
        sa.Column("purpose", sa.Text(), primary_key=True, server_default="INITIAL"),
        sa.Column("fact_version", sa.BigInteger(), nullable=False),
        sa.Column("initialization_id", sa.Uuid(), nullable=False),
        sa.Column("from_date", sa.Date(), nullable=False),
        sa.Column("scan_through_date", sa.Date(), nullable=False),
        sa.Column("current_date", sa.Date(), nullable=False),
        sa.Column("complete_through", sa.Date()),
        sa.Column("after_stock", sa.Text()),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("evidence", JSONB()),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("transient_failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id", "initialization_id"],
            ["app.wealth_ta_initialization.account_id", "app.wealth_ta_initialization.initialization_id"], ondelete="RESTRICT"),
        sa.CheckConstraint("target_version > 0 AND fact_version > 0 AND transient_failure_count >= 0", name="versions"),
        sa.CheckConstraint("purpose IN ('INITIAL', 'DISCOVERY', 'HISTORY')", name="purpose"),
        sa.CheckConstraint('from_date <= "current_date" AND (complete_through IS NULL OR '
            '(complete_through >= from_date AND complete_through < "current_date"))', name="dates"),
        sa.CheckConstraint("state IN ('SCANNING', 'WAITING_DATA', 'READY', 'FAILED', 'CHANGED') AND "
            "(state <> 'READY' OR complete_through IS NOT NULL)", name="state"),
        sa.CheckConstraint("(state = 'CHANGED' AND purpose = 'HISTORY' AND evidence IS NOT NULL) OR "
            "(state <> 'CHANGED' AND evidence IS NULL)", name="change_evidence"), schema="app")
    op.create_table("wealth_ta_cutoff_discovery_cursor",
        sa.Column("singleton_id", sa.Integer(), primary_key=True),
        sa.Column("after_account_id", sa.Uuid()),
        sa.Column("cycle_progress", sa.Boolean(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("singleton_id IN (1, 2)", name="singleton"), schema="app")
    op.execute("INSERT INTO app.wealth_ta_cutoff_discovery_cursor "
        "(singleton_id, cycle_progress, next_attempt_at) VALUES "
        "(1, false, clock_timestamp()), (2, false, clock_timestamp())")


def downgrade():
    raise RuntimeError("Retained cutoff evidence must not be dropped by an automatic downgrade")
