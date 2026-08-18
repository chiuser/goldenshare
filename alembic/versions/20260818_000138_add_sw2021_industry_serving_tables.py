"""add SW2021 industry serving tables

Revision ID: 20260818_000138
Revises: 20260816_000137
Create Date: 2026-08-18
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260818_000138"
down_revision = "20260816_000137"
branch_labels = None
depends_on = None

_SCHEMA = "core_serving"


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.create_table(
        "sw_industry_classification",
        sa.Column("src", sa.String(length=16), nullable=False),
        sa.Column("industry_code", sa.String(length=16), nullable=False),
        sa.Column("source_index_code", sa.String(length=16), nullable=False),
        sa.Column("index_code", sa.String(length=16), nullable=False),
        sa.Column("industry_name", sa.String(length=64), nullable=False),
        sa.Column("source_parent_code", sa.String(length=16), nullable=True),
        sa.Column("parent_code", sa.String(length=16), nullable=True),
        sa.Column("level", sa.String(length=2), nullable=False),
        sa.Column("is_pub", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("normalization_rule_version", sa.String(length=64), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint(
            "src", "industry_code", name=op.f("pk_sw_industry_classification")
        ),
        sa.UniqueConstraint(
            "src", "index_code", name="uq_sw_industry_classification_src_index_code"
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "idx_sw_industry_classification_src_level_pub",
        "sw_industry_classification",
        ["src", "level", "is_pub"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "idx_sw_industry_classification_src_parent",
        "sw_industry_classification",
        ["src", "parent_code"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "sw_industry_member",
        sa.Column("l3_code", sa.String(length=16), nullable=False),
        sa.Column("ts_code", sa.String(length=16), nullable=False),
        sa.Column("in_date", sa.Date(), nullable=False),
        sa.Column("source_l1_code", sa.String(length=16), nullable=False),
        sa.Column("l1_code", sa.String(length=16), nullable=False),
        sa.Column("l1_name", sa.String(length=64), nullable=False),
        sa.Column("source_l2_code", sa.String(length=16), nullable=False),
        sa.Column("l2_code", sa.String(length=16), nullable=False),
        sa.Column("l2_name", sa.String(length=64), nullable=False),
        sa.Column("source_l3_code", sa.String(length=16), nullable=False),
        sa.Column("l3_name", sa.String(length=64), nullable=False),
        sa.Column("stock_name", sa.String(length=64), nullable=False),
        sa.Column("out_date", sa.Date(), nullable=True),
        sa.Column("is_new", sa.Boolean(), nullable=False),
        sa.Column("classification_version", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("normalization_rule_version", sa.String(length=64), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "out_date IS NULL OR out_date >= in_date",
            name=op.f("ck_sw_industry_member_out_date_not_before_in_date"),
        ),
        sa.ForeignKeyConstraint(
            ["classification_version", "l3_code"],
            [
                "core_serving.sw_industry_classification.src",
                "core_serving.sw_industry_classification.index_code",
            ],
            name="fk_sw_industry_member_classification_l3",
        ),
        sa.PrimaryKeyConstraint(
            "l3_code", "ts_code", "in_date", name=op.f("pk_sw_industry_member")
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "idx_sw_industry_member_l3_current_stock",
        "sw_industry_member",
        ["l3_code", "is_new", "ts_code"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "idx_sw_industry_member_l3_membership_dates",
        "sw_industry_member",
        ["l3_code", "in_date", "out_date"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "idx_sw_industry_member_stock_membership_dates",
        "sw_industry_member",
        ["ts_code", "in_date", "out_date"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "sw_industry_daily",
        sa.Column("ts_code", sa.String(length=16), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("source_ts_code", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("change", sa.Float(), nullable=True),
        sa.Column("pct_change", sa.Float(), nullable=True),
        sa.Column("vol", sa.Float(), nullable=True),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("pe", sa.Float(), nullable=True),
        sa.Column("pb", sa.Float(), nullable=True),
        sa.Column("float_mv", sa.Float(), nullable=True),
        sa.Column("total_mv", sa.Float(), nullable=True),
        sa.Column("classification_version", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("normalization_rule_version", sa.String(length=64), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint(
            "ts_code", "trade_date", name=op.f("pk_sw_industry_daily")
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "idx_sw_industry_daily_trade_code",
        "sw_industry_daily",
        ["trade_date", "ts_code"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "idx_sw_industry_daily_code_trade_desc",
        "sw_industry_daily",
        ["ts_code", sa.text("trade_date DESC")],
        unique=False,
        schema=_SCHEMA,
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.drop_index(
        "idx_sw_industry_daily_code_trade_desc",
        table_name="sw_industry_daily",
        schema=_SCHEMA,
    )
    op.drop_index(
        "idx_sw_industry_daily_trade_code",
        table_name="sw_industry_daily",
        schema=_SCHEMA,
    )
    op.drop_table("sw_industry_daily", schema=_SCHEMA)
    op.drop_index(
        "idx_sw_industry_member_stock_membership_dates",
        table_name="sw_industry_member",
        schema=_SCHEMA,
    )
    op.drop_index(
        "idx_sw_industry_member_l3_membership_dates",
        table_name="sw_industry_member",
        schema=_SCHEMA,
    )
    op.drop_index(
        "idx_sw_industry_member_l3_current_stock",
        table_name="sw_industry_member",
        schema=_SCHEMA,
    )
    op.drop_table("sw_industry_member", schema=_SCHEMA)
    op.drop_index(
        "idx_sw_industry_classification_src_parent",
        table_name="sw_industry_classification",
        schema=_SCHEMA,
    )
    op.drop_index(
        "idx_sw_industry_classification_src_level_pub",
        table_name="sw_industry_classification",
        schema=_SCHEMA,
    )
    op.drop_table("sw_industry_classification", schema=_SCHEMA)
