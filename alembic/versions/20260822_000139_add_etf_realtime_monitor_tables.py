"""add ETF realtime monitor tables

Revision ID: 20260822_000139
Revises: 20260818_000138
Create Date: 2026-08-22
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260822_000139"
down_revision = "20260818_000138"
branch_labels = None
depends_on = None

_SCHEMA = "ops"


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.create_table(
        "etf_realtime_monitor_pool",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ts_code", sa.String(length=16), nullable=False),
        sa.Column("group_key", sa.String(length=64), nullable=False),
        sa.Column("group_name", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("display_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("updated_by_user_id", sa.BigInteger(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_etf_realtime_monitor_pool")),
        schema=_SCHEMA,
    )
    op.create_index("uq_etf_realtime_monitor_pool_ts_code", "etf_realtime_monitor_pool", ["ts_code"], unique=True, schema=_SCHEMA)
    op.create_index("idx_etf_realtime_monitor_pool_group_enabled", "etf_realtime_monitor_pool", ["group_key", "enabled"], unique=False, schema=_SCHEMA)
    op.create_index("idx_etf_realtime_monitor_pool_enabled_order", "etf_realtime_monitor_pool", ["enabled", "display_order"], unique=False, schema=_SCHEMA)

    op.create_table(
        "etf_realtime_monitor_rule",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column("scope_key", sa.String(length=64), nullable=False),
        sa.Column("window_minutes", sa.SmallInteger(), nullable=False),
        sa.Column("observe_ratio", sa.Numeric(10, 4), nullable=False),
        sa.Column("alert_ratio", sa.Numeric(10, 4), nullable=False),
        sa.Column("strong_ratio", sa.Numeric(10, 4), nullable=False),
        sa.Column("cooldown_minutes", sa.Integer(), nullable=False),
        sa.Column("feishu_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("updated_by_user_id", sa.BigInteger(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("scope_type in ('global', 'group', 'etf')", name=op.f("ck_etf_realtime_monitor_rule_scope_type_valid")),
        sa.CheckConstraint("window_minutes in (1, 5, 15)", name=op.f("ck_etf_realtime_monitor_rule_window_minutes_valid")),
        sa.CheckConstraint("observe_ratio > 0", name=op.f("ck_etf_realtime_monitor_rule_observe_ratio_positive")),
        sa.CheckConstraint("observe_ratio <= alert_ratio", name=op.f("ck_etf_realtime_monitor_rule_observe_not_above_alert")),
        sa.CheckConstraint("alert_ratio <= strong_ratio", name=op.f("ck_etf_realtime_monitor_rule_alert_not_above_strong")),
        sa.CheckConstraint("cooldown_minutes > 0", name=op.f("ck_etf_realtime_monitor_rule_cooldown_minutes_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_etf_realtime_monitor_rule")),
        schema=_SCHEMA,
    )
    op.create_index(
        "uq_etf_realtime_monitor_rule_scope_window",
        "etf_realtime_monitor_rule",
        ["scope_type", "scope_key", "window_minutes"],
        unique=True,
        schema=_SCHEMA,
    )
    op.create_index("idx_etf_realtime_monitor_rule_enabled", "etf_realtime_monitor_rule", ["enabled"], unique=False, schema=_SCHEMA)

    op.create_table(
        "etf_realtime_minute_stat",
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("minute_bucket", sa.Time(), nullable=False),
        sa.Column("ts_code", sa.String(length=16), nullable=False),
        sa.Column("source_trade_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_batch_id", sa.String(length=64), nullable=True),
        sa.Column("previous_batch_id", sa.String(length=64), nullable=True),
        sa.Column("cumulative_amount_yuan", sa.Numeric(24, 4), nullable=True),
        sa.Column("amount_delta_yuan", sa.Numeric(24, 4), nullable=True),
        sa.Column("cumulative_vol", sa.Numeric(24, 4), nullable=True),
        sa.Column("vol_delta", sa.Numeric(24, 4), nullable=True),
        sa.Column("data_quality", sa.String(length=16), nullable=False),
        sa.Column("missing_reason", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("trade_date", "minute_bucket", "ts_code", name=op.f("pk_etf_realtime_minute_stat")),
        schema=_SCHEMA,
    )
    op.create_index("idx_etf_realtime_minute_stat_code_date", "etf_realtime_minute_stat", ["ts_code", "trade_date"], unique=False, schema=_SCHEMA)
    op.create_index("idx_etf_realtime_minute_stat_date_bucket", "etf_realtime_minute_stat", ["trade_date", "minute_bucket"], unique=False, schema=_SCHEMA)
    op.create_index("idx_etf_realtime_minute_stat_quality_date", "etf_realtime_minute_stat", ["data_quality", "trade_date"], unique=False, schema=_SCHEMA)

    op.create_table(
        "etf_realtime_alert",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bucket_end_time", sa.Time(), nullable=False),
        sa.Column("window_minutes", sa.SmallInteger(), nullable=False),
        sa.Column("ts_code", sa.String(length=16), nullable=False),
        sa.Column("etf_name", sa.String(length=128), nullable=True),
        sa.Column("group_key", sa.String(length=64), nullable=False),
        sa.Column("group_name", sa.String(length=64), nullable=False),
        sa.Column("rule_id", sa.BigInteger(), nullable=True),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("current_amount_yuan", sa.Numeric(24, 4), nullable=False),
        sa.Column("baseline_amount_yuan", sa.Numeric(24, 4), nullable=False),
        sa.Column("ratio", sa.Numeric(12, 4), nullable=False),
        sa.Column("baseline_trade_dates_json", sa.JSON(), nullable=False),
        sa.Column("cooldown_key", sa.String(length=256), nullable=False),
        sa.Column("feishu_status", sa.String(length=16), nullable=False),
        sa.Column("feishu_message_id", sa.String(length=128), nullable=True),
        sa.Column("feishu_error", sa.Text(), nullable=True),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_etf_realtime_alert")),
        schema=_SCHEMA,
    )
    op.create_index("idx_etf_realtime_alert_date_code_window", "etf_realtime_alert", ["trade_date", "ts_code", "window_minutes"], unique=False, schema=_SCHEMA)
    op.create_index("idx_etf_realtime_alert_triggered_at", "etf_realtime_alert", ["triggered_at"], unique=False, schema=_SCHEMA)
    op.create_index("idx_etf_realtime_alert_severity_triggered", "etf_realtime_alert", ["severity", "triggered_at"], unique=False, schema=_SCHEMA)
    op.create_index("idx_etf_realtime_alert_cooldown_triggered", "etf_realtime_alert", ["cooldown_key", "triggered_at"], unique=False, schema=_SCHEMA)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.drop_index("idx_etf_realtime_alert_cooldown_triggered", table_name="etf_realtime_alert", schema=_SCHEMA)
    op.drop_index("idx_etf_realtime_alert_severity_triggered", table_name="etf_realtime_alert", schema=_SCHEMA)
    op.drop_index("idx_etf_realtime_alert_triggered_at", table_name="etf_realtime_alert", schema=_SCHEMA)
    op.drop_index("idx_etf_realtime_alert_date_code_window", table_name="etf_realtime_alert", schema=_SCHEMA)
    op.drop_table("etf_realtime_alert", schema=_SCHEMA)
    op.drop_index("idx_etf_realtime_minute_stat_quality_date", table_name="etf_realtime_minute_stat", schema=_SCHEMA)
    op.drop_index("idx_etf_realtime_minute_stat_date_bucket", table_name="etf_realtime_minute_stat", schema=_SCHEMA)
    op.drop_index("idx_etf_realtime_minute_stat_code_date", table_name="etf_realtime_minute_stat", schema=_SCHEMA)
    op.drop_table("etf_realtime_minute_stat", schema=_SCHEMA)
    op.drop_index("idx_etf_realtime_monitor_rule_enabled", table_name="etf_realtime_monitor_rule", schema=_SCHEMA)
    op.drop_index("uq_etf_realtime_monitor_rule_scope_window", table_name="etf_realtime_monitor_rule", schema=_SCHEMA)
    op.drop_table("etf_realtime_monitor_rule", schema=_SCHEMA)
    op.drop_index("idx_etf_realtime_monitor_pool_enabled_order", table_name="etf_realtime_monitor_pool", schema=_SCHEMA)
    op.drop_index("idx_etf_realtime_monitor_pool_group_enabled", table_name="etf_realtime_monitor_pool", schema=_SCHEMA)
    op.drop_index("uq_etf_realtime_monitor_pool_ts_code", table_name="etf_realtime_monitor_pool", schema=_SCHEMA)
    op.drop_table("etf_realtime_monitor_pool", schema=_SCHEMA)
