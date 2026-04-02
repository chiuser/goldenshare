"""widen ths_daily numeric columns to avoid overflow"""

from __future__ import annotations

from alembic import op


revision = "20260402_000024"
down_revision = "20260402_000023"
branch_labels = None
depends_on = None


def _alter(schema: str, table: str, column: str, precision: int, scale: int) -> None:
    op.execute(
        f"ALTER TABLE {schema}.{table} ALTER COLUMN {column} TYPE NUMERIC({precision},{scale}) "
        f"USING {column}::numeric({precision},{scale})"
    )


def upgrade() -> None:
    for schema in ("raw", "core"):
        _alter(schema, "ths_daily", "close", 24, 6)
        _alter(schema, "ths_daily", "open", 24, 6)
        _alter(schema, "ths_daily", "high", 24, 6)
        _alter(schema, "ths_daily", "low", 24, 6)
        _alter(schema, "ths_daily", "pre_close", 24, 6)
        _alter(schema, "ths_daily", "avg_price", 24, 6)
        _alter(schema, "ths_daily", "change", 24, 6)
        _alter(schema, "ths_daily", "pct_change", 18, 6)
        _alter(schema, "ths_daily", "vol", 30, 4)
        _alter(schema, "ths_daily", "turnover_rate", 18, 6)
        _alter(schema, "ths_daily", "total_mv", 30, 4)
        _alter(schema, "ths_daily", "float_mv", 30, 4)


def downgrade() -> None:
    for schema in ("raw", "core"):
        _alter(schema, "ths_daily", "close", 18, 4)
        _alter(schema, "ths_daily", "open", 18, 4)
        _alter(schema, "ths_daily", "high", 18, 4)
        _alter(schema, "ths_daily", "low", 18, 4)
        _alter(schema, "ths_daily", "pre_close", 18, 4)
        _alter(schema, "ths_daily", "avg_price", 18, 4)
        _alter(schema, "ths_daily", "change", 18, 4)
        _alter(schema, "ths_daily", "pct_change", 10, 4)
        _alter(schema, "ths_daily", "vol", 20, 4)
        _alter(schema, "ths_daily", "turnover_rate", 12, 4)
        _alter(schema, "ths_daily", "total_mv", 20, 4)
        _alter(schema, "ths_daily", "float_mv", 20, 4)
