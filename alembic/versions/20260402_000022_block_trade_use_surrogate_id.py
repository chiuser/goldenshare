"""use surrogate id for block_trade tables"""

from __future__ import annotations

from alembic import op


revision = "20260402_000022"
down_revision = "20260402_000021"
branch_labels = None
depends_on = None


def _upgrade_table(schema: str, table: str) -> None:
    seq_name = f"{table}_id_seq"
    op.execute(f"CREATE SEQUENCE IF NOT EXISTS {schema}.{seq_name}")
    op.execute(f"ALTER TABLE {schema}.{table} ADD COLUMN IF NOT EXISTS id BIGINT")
    op.execute(f"ALTER TABLE {schema}.{table} ALTER COLUMN id SET DEFAULT nextval('{schema}.{seq_name}')")
    op.execute(f"UPDATE {schema}.{table} SET id = nextval('{schema}.{seq_name}') WHERE id IS NULL")
    op.execute(
        f"SELECT setval('{schema}.{seq_name}', COALESCE((SELECT MAX(id) FROM {schema}.{table}), 0) + 1, false)"
    )
    op.execute(f"ALTER TABLE {schema}.{table} ALTER COLUMN id SET NOT NULL")
    op.execute(f"ALTER TABLE {schema}.{table} DROP CONSTRAINT IF EXISTS {table}_pkey")
    op.execute(f"ALTER TABLE {schema}.{table} ADD CONSTRAINT {table}_pkey PRIMARY KEY (id)")


def _downgrade_table(schema: str, table: str) -> None:
    # 降级时回到复合主键，先清理重复键以满足旧约束。
    op.execute(
        f"""
        DELETE FROM {schema}.{table} t
        USING (
          SELECT id,
                 ROW_NUMBER() OVER (
                   PARTITION BY ts_code, trade_date, buyer, seller, price, vol
                   ORDER BY id
                 ) AS rn
          FROM {schema}.{table}
        ) d
        WHERE t.id = d.id AND d.rn > 1
        """
    )
    op.execute(f"ALTER TABLE {schema}.{table} DROP CONSTRAINT IF EXISTS {table}_pkey")
    op.execute(
        f"""
        ALTER TABLE {schema}.{table}
        ADD CONSTRAINT {table}_pkey
        PRIMARY KEY (ts_code, trade_date, buyer, seller, price, vol)
        """
    )
    op.execute(f"ALTER TABLE {schema}.{table} ALTER COLUMN id DROP DEFAULT")
    op.execute(f"ALTER TABLE {schema}.{table} DROP COLUMN IF EXISTS id")
    op.execute(f"DROP SEQUENCE IF EXISTS {schema}.{table}_id_seq")


def upgrade() -> None:
    _upgrade_table("raw", "block_trade")
    _upgrade_table("core", "equity_block_trade")


def downgrade() -> None:
    _downgrade_table("core", "equity_block_trade")
    _downgrade_table("raw", "block_trade")
