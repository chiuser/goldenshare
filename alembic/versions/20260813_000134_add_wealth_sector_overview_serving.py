"""add wealth sector overview serving tables

Revision ID: 20260813_000134
Revises: 20260812_000133
Create Date: 2026-08-13
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260813_000134"
down_revision = "20260812_000133"
branch_labels = None
depends_on = None


_SCHEMA = "core_serving"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.create_table(
        "wealth_sector_hierarchy",
        sa.Column("sector_code", sa.String(length=16), nullable=False),
        sa.Column("sector_name", sa.String(length=128), nullable=False),
        sa.Column("industry_level", sa.SmallInteger(), nullable=False),
        sa.Column("industry_level_name", sa.String(length=32), nullable=False),
        sa.Column("parent_sector_code", sa.String(length=16), nullable=True),
        sa.Column("parent_sector_name", sa.String(length=128), nullable=True),
        sa.Column("root_sector_code", sa.String(length=16), nullable=False),
        sa.Column("root_sector_name", sa.String(length=128), nullable=False),
        sa.Column("hierarchy_path", sa.String(length=512), nullable=False),
        sa.Column("is_leaf", sa.Boolean(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("baseline_version", sa.String(length=128), nullable=False),
        sa.Column("source_received_date", sa.Date(), nullable=False),
        sa.Column("code_reference_trade_date", sa.Date(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "industry_level BETWEEN 1 AND 3",
            name=op.f("ck_wealth_sector_hierarchy_industry_level_range"),
        ),
        sa.CheckConstraint(
            "display_order >= 0",
            name=op.f("ck_wealth_sector_hierarchy_display_order_non_negative"),
        ),
        sa.CheckConstraint(
            "(industry_level = 1 AND parent_sector_code IS NULL AND parent_sector_name IS NULL) "
            "OR (industry_level IN (2, 3) AND parent_sector_code IS NOT NULL "
            "AND parent_sector_name IS NOT NULL)",
            name=op.f("ck_wealth_sector_hierarchy_parent_fields_by_level"),
        ),
        sa.PrimaryKeyConstraint(
            "sector_code",
            name=op.f("pk_wealth_sector_hierarchy"),
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "idx_wealth_sector_hierarchy_level_order_code",
        "wealth_sector_hierarchy",
        ["industry_level", "display_order", "sector_code"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "idx_wealth_sector_hierarchy_parent_level_order_code",
        "wealth_sector_hierarchy",
        ["parent_sector_code", "industry_level", "display_order", "sector_code"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "idx_wealth_sector_hierarchy_root_level_order_code",
        "wealth_sector_hierarchy",
        ["root_sector_code", "industry_level", "display_order", "sector_code"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "wealth_sector_heat_daily",
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("sector_code", sa.String(length=16), nullable=False),
        sa.Column("sector_name", sa.String(length=128), nullable=False),
        sa.Column("heat_status", sa.String(length=16), nullable=False),
        sa.Column("invalid_reason", sa.String(length=64), nullable=True),
        sa.Column("base_heat_score", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("base_heat_rank", sa.Integer(), nullable=True),
        sa.Column("heat_score", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("heat_rank", sa.Integer(), nullable=True),
        sa.Column("heat_level", sa.String(length=16), nullable=False),
        sa.Column("heat_delta_1d", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("heat_trend", sa.String(length=16), nullable=False),
        sa.Column("raw_heat_trend", sa.String(length=16), nullable=False),
        sa.Column("price_strength_score", sa.Numeric(precision=8, scale=6), nullable=True),
        sa.Column("breadth_score", sa.Numeric(precision=8, scale=6), nullable=True),
        sa.Column("capital_flow_score", sa.Numeric(precision=8, scale=6), nullable=True),
        sa.Column("activity_score", sa.Numeric(precision=8, scale=6), nullable=True),
        sa.Column("persistence_score", sa.Numeric(precision=8, scale=6), nullable=True),
        sa.Column("source_member_count", sa.Integer(), nullable=False),
        sa.Column("member_count", sa.Integer(), nullable=False),
        sa.Column("suspended_count", sa.Integer(), nullable=False),
        sa.Column("quote_eligible_count", sa.Integer(), nullable=False),
        sa.Column("valid_quote_count", sa.Integer(), nullable=False),
        sa.Column("missing_quote_count", sa.Integer(), nullable=False),
        sa.Column("quote_coverage", sa.Numeric(precision=8, scale=6), nullable=False),
        sa.Column("score_version", sa.String(length=64), nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column("source_dates_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_row_counts_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "heat_status IN ('VALID', 'INVALID')",
            name=op.f("ck_wealth_sector_heat_daily_heat_status_allowed"),
        ),
        sa.CheckConstraint(
            "(heat_status = 'VALID' AND invalid_reason IS NULL) OR "
            "(heat_status = 'INVALID' AND invalid_reason IN ("
            "'MEMBER_COUNT_LOW', 'QUOTE_ELIGIBLE_COUNT_ZERO', 'QUOTE_COVERAGE_LOW', "
            "'HISTORY_INSUFFICIENT', 'FEATURE_MISSING'))",
            name=op.f("ck_wealth_sector_heat_daily_status_reason_consistent"),
        ),
        sa.CheckConstraint(
            "heat_level IN ('BOILING', 'HOT', 'ACTIVE', 'NONE')",
            name=op.f("ck_wealth_sector_heat_daily_heat_level_allowed"),
        ),
        sa.CheckConstraint(
            "heat_trend IN ('HEATING', 'STABLE', 'COOLING', 'UNKNOWN')",
            name=op.f("ck_wealth_sector_heat_daily_heat_trend_allowed"),
        ),
        sa.CheckConstraint(
            "raw_heat_trend IN ('HEATING', 'STABLE', 'COOLING', 'UNKNOWN')",
            name=op.f("ck_wealth_sector_heat_daily_raw_heat_trend_allowed"),
        ),
        sa.CheckConstraint(
            "heat_status <> 'VALID' OR ("
            "base_heat_score IS NOT NULL AND base_heat_rank IS NOT NULL "
            "AND heat_score IS NOT NULL AND heat_rank IS NOT NULL "
            "AND price_strength_score IS NOT NULL AND breadth_score IS NOT NULL "
            "AND capital_flow_score IS NOT NULL AND activity_score IS NOT NULL "
            "AND persistence_score IS NOT NULL)",
            name=op.f("ck_wealth_sector_heat_daily_valid_metrics_present"),
        ),
        sa.CheckConstraint(
            "heat_status <> 'INVALID' OR ("
            "heat_score IS NULL AND heat_rank IS NULL AND heat_level = 'NONE' "
            "AND heat_delta_1d IS NULL AND heat_trend = 'UNKNOWN' "
            "AND raw_heat_trend = 'UNKNOWN')",
            name=op.f("ck_wealth_sector_heat_daily_invalid_outputs_empty"),
        ),
        sa.CheckConstraint(
            "(base_heat_score IS NULL OR base_heat_score BETWEEN 0 AND 100) "
            "AND (heat_score IS NULL OR heat_score BETWEEN 0 AND 100)",
            name=op.f("ck_wealth_sector_heat_daily_heat_scores_range"),
        ),
        sa.CheckConstraint(
            "(price_strength_score IS NULL OR price_strength_score BETWEEN 0 AND 1) "
            "AND (breadth_score IS NULL OR breadth_score BETWEEN 0 AND 1) "
            "AND (capital_flow_score IS NULL OR capital_flow_score BETWEEN 0 AND 1) "
            "AND (activity_score IS NULL OR activity_score BETWEEN 0 AND 1) "
            "AND (persistence_score IS NULL OR persistence_score BETWEEN 0 AND 1) "
            "AND quote_coverage BETWEEN 0 AND 1",
            name=op.f("ck_wealth_sector_heat_daily_component_scores_range"),
        ),
        sa.CheckConstraint(
            "(base_heat_rank IS NULL OR base_heat_rank > 0) "
            "AND (heat_rank IS NULL OR heat_rank > 0)",
            name=op.f("ck_wealth_sector_heat_daily_heat_ranks_positive"),
        ),
        sa.CheckConstraint(
            "source_member_count >= 0 AND member_count >= 0 AND suspended_count >= 0 "
            "AND quote_eligible_count >= 0 AND valid_quote_count >= 0 "
            "AND missing_quote_count >= 0",
            name=op.f("ck_wealth_sector_heat_daily_member_counts_non_negative"),
        ),
        sa.CheckConstraint(
            "suspended_count <= member_count",
            name=op.f("ck_wealth_sector_heat_daily_suspended_count_within_members"),
        ),
        sa.CheckConstraint(
            "quote_eligible_count = member_count - suspended_count",
            name=op.f("ck_wealth_sector_heat_daily_quote_eligible_count_consistent"),
        ),
        sa.CheckConstraint(
            "valid_quote_count <= quote_eligible_count",
            name=op.f("ck_wealth_sector_heat_daily_valid_quote_count_within_eligible"),
        ),
        sa.CheckConstraint(
            "missing_quote_count = quote_eligible_count - valid_quote_count",
            name=op.f("ck_wealth_sector_heat_daily_missing_quote_count_consistent"),
        ),
        sa.CheckConstraint(
            "config_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_wealth_sector_heat_daily_config_hash_sha256"),
        ),
        sa.CheckConstraint(
            "source_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_wealth_sector_heat_daily_source_hash_sha256"),
        ),
        sa.PrimaryKeyConstraint(
            "trade_date",
            "sector_code",
            name=op.f("pk_wealth_sector_heat_daily"),
        ),
        schema=_SCHEMA,
    )
    op.execute(
        "CREATE INDEX idx_wealth_sector_heat_daily_trade_score_code "
        "ON core_serving.wealth_sector_heat_daily (trade_date, heat_score DESC, sector_code)"
    )
    op.execute(
        "CREATE INDEX idx_wealth_sector_heat_daily_trade_delta_code "
        "ON core_serving.wealth_sector_heat_daily (trade_date, heat_delta_1d DESC, sector_code)"
    )
    op.execute(
        "CREATE INDEX idx_wealth_sector_heat_daily_sector_trade "
        "ON core_serving.wealth_sector_heat_daily (sector_code, trade_date DESC)"
    )
    op.execute(
        "GRANT SELECT, INSERT, DELETE ON TABLE "
        "core_serving.wealth_sector_hierarchy TO lake_raw_writer"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.drop_table("wealth_sector_heat_daily", schema=_SCHEMA)
    op.drop_table("wealth_sector_hierarchy", schema=_SCHEMA)
