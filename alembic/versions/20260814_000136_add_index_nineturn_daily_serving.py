"""add index nineturn daily serving table

Revision ID: 20260814_000136
Revises: 20260813_000135
Create Date: 2026-08-14
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260814_000136"
down_revision = "20260813_000135"
branch_labels = None
depends_on = None

_SCHEMA = "core_serving"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.create_table(
        "index_nineturn_daily",
        sa.Column("ts_code", sa.String(length=16), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("up_count", sa.Integer(), nullable=False),
        sa.Column("down_count", sa.Integer(), nullable=False),
        sa.Column("nine_up_turn", sa.String(length=2), nullable=True),
        sa.Column("nine_down_turn", sa.String(length=2), nullable=True),
        sa.Column("formula_version", sa.SmallInteger(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "close > 0 AND close < 1e308",
            name=op.f("ck_index_nineturn_daily_close_positive"),
        ),
        sa.CheckConstraint(
            "up_count >= 0 AND down_count >= 0",
            name=op.f("ck_index_nineturn_daily_counts_non_negative"),
        ),
        sa.CheckConstraint(
            "NOT (up_count > 0 AND down_count > 0)",
            name=op.f("ck_index_nineturn_daily_single_direction"),
        ),
        sa.CheckConstraint(
            "nine_up_turn IS NULL OR nine_up_turn = '+9'",
            name=op.f("ck_index_nineturn_daily_up_signal_allowed"),
        ),
        sa.CheckConstraint(
            "nine_down_turn IS NULL OR nine_down_turn = '-9'",
            name=op.f("ck_index_nineturn_daily_down_signal_allowed"),
        ),
        sa.CheckConstraint(
            "nine_up_turn IS NULL OR up_count >= 9",
            name=op.f("ck_index_nineturn_daily_up_signal_count"),
        ),
        sa.CheckConstraint(
            "nine_down_turn IS NULL OR down_count >= 9",
            name=op.f("ck_index_nineturn_daily_down_signal_count"),
        ),
        sa.CheckConstraint(
            "NOT (nine_up_turn IS NOT NULL AND nine_down_turn IS NOT NULL)",
            name=op.f("ck_index_nineturn_daily_single_signal"),
        ),
        sa.CheckConstraint(
            "formula_version = 1",
            name=op.f("ck_index_nineturn_daily_formula_version"),
        ),
        sa.PrimaryKeyConstraint(
            "ts_code", "trade_date", name=op.f("pk_index_nineturn_daily")
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "idx_index_nineturn_daily_trade_code",
        "index_nineturn_daily",
        ["trade_date", "ts_code"],
        unique=False,
        schema=_SCHEMA,
    )
    op.execute(
        "GRANT SELECT, INSERT, DELETE ON TABLE "
        "core_serving.index_nineturn_daily TO lake_raw_writer"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.drop_index(
        "idx_index_nineturn_daily_trade_code",
        table_name="index_nineturn_daily",
        schema=_SCHEMA,
    )
    op.drop_table("index_nineturn_daily", schema=_SCHEMA)
