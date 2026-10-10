"""Add the dedicated append-only weekly delivery table. No historical data changes."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261010_000185"
down_revision = "20261008_000184"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "stock_weekly_adj_delivery",
        sa.Column("revision", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("contract_version", sa.SmallInteger(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("unit_id", sa.String(128), nullable=False),
        sa.Column("record_kind", sa.String(24), nullable=False),
        sa.Column("intent", postgresql.JSONB(), nullable=False),
        sa.Column("unit_kind", sa.String(24), nullable=True),
        sa.Column("cutoff_week", sa.Date(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("ts_code", sa.String(16), nullable=True),
        sa.Column("factor_scan_start", sa.Date(), nullable=True),
        sa.Column("factor_scan_end", sa.Date(), nullable=True),
        sa.Column("factor_target", sa.Numeric(20, 8), nullable=True),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("rows_received", sa.BigInteger(), nullable=False),
        sa.Column("rows_unique", sa.BigInteger(), nullable=False),
        sa.Column("rows_written", sa.BigInteger(), nullable=False),
        sa.Column("rows_preserved", sa.BigInteger(), nullable=False),
        sa.Column("basis_date", sa.Date(), nullable=True),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column("scope_digest", sa.String(64), nullable=False),
        sa.Column("reason_summary", postgresql.JSONB(), nullable=False),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("revision", name="pk_stock_weekly_adj_delivery"),
        sa.UniqueConstraint(
            "batch_id", "record_kind", "unit_id", name="uq_weekly_adj_delivery_unit"
        ),
        sa.CheckConstraint(
            "contract_version = 1",
            name="ck_stock_weekly_adj_delivery_weekly_adj_delivery_version",
        ),
        sa.CheckConstraint(
            "record_kind IN ('plan','unit','batch_closed','bootstrap_closed')",
            name="ck_stock_weekly_adj_delivery_weekly_adj_delivery_kind",
        ),
        sa.CheckConstraint(
            "outcome IN ('published','source_empty_preserved','partial_source_preserved','no_trading_week')",
            name="ck_stock_weekly_adj_delivery_weekly_adj_delivery_outcome",
        ),
        sa.CheckConstraint(
            "rows_received >= 0 AND rows_unique >= 0 AND rows_written >= 0 AND rows_preserved >= 0",
            name="ck_stock_weekly_adj_delivery_weekly_adj_delivery_counts",
        ),
        sa.CheckConstraint(
            "octet_length(payload::text) <= CASE WHEN record_kind = 'plan' THEN 1048576 ELSE 8388608 END",
            name="ck_stock_weekly_adj_delivery_weekly_adj_delivery_payload_bytes",
        ),
        schema="core",
    )
    op.create_index(
        "idx_weekly_adj_delivery_kind_revision",
        "stock_weekly_adj_delivery",
        ["record_kind", "revision"],
        schema="core",
    )
    op.execute("""CREATE FUNCTION core.reject_stock_weekly_adj_delivery_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            RAISE EXCEPTION 'stock_weekly_adj_delivery is append-only';
        END $$""")
    op.execute("""CREATE TRIGGER stock_weekly_adj_delivery_append_only
        BEFORE UPDATE OR DELETE ON core.stock_weekly_adj_delivery
        FOR EACH ROW EXECUTE FUNCTION core.reject_stock_weekly_adj_delivery_mutation()""")


def downgrade():
    raise RuntimeError(
        "Deleting weekly business delivery records requires a separately approved operation"
    )
