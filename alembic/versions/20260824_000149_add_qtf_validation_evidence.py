"""add QTF validation evidence and conclusion state

Revision ID: 20260824_000149
Revises: 20260824_000148
Create Date: 2026-08-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260824_000149"
down_revision = "20260824_000148"
branch_labels = None
depends_on = None

_SCHEMA = "qtf"


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
        "run_gate_result",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("gate_key", sa.String(length=48), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "gate_key in ('INPUT', 'TIME_FRONTIER', 'FUTURE_LEAKAGE', 'WARMUP', "
            "'COVERAGE', 'OUT_OF_SAMPLE_SENSITIVITY')",
            name="ck_qtf_run_gate_result_gate_valid",
        ),
        sa.CheckConstraint(
            "status in ('PASS', 'FAIL', 'INSUFFICIENT')",
            name="ck_qtf_run_gate_result_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["qtf.experiment_run.id"],
            name="fk_qtf_run_gate_result_run_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_qtf_run_gate_result"),
        sa.UniqueConstraint(
            "run_id",
            "gate_key",
            name="uq_qtf_run_gate_result_run_gate",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "idx_qtf_run_gate_result_run",
        "run_gate_result",
        ["run_id", "gate_key"],
        schema=_SCHEMA,
    )

    op.create_table(
        "run_parameter_result",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("result_key", sa.String(length=96), nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("parameter_set_key", sa.String(length=96), nullable=False),
        sa.Column("parameter_values_json", sa.JSON(), nullable=False),
        sa.Column("entry_metrics_json", sa.JSON(), nullable=False),
        sa.Column("retention_metrics_json", sa.JSON(), nullable=False),
        sa.Column("baseline_metrics_json", sa.JSON(), nullable=False),
        sa.Column("lift_metrics_json", sa.JSON(), nullable=False),
        sa.Column("coverage_metrics_json", sa.JSON(), nullable=False),
        sa.Column("sample_metrics_json", sa.JSON(), nullable=False),
        sa.Column("confidence_intervals_json", sa.JSON(), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        sa.Column("effect_status", sa.String(length=24), nullable=False),
        sa.Column("result_hash", sa.String(length=64), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "effect_status in ('SUPPORTED', 'REJECTED', 'INSUFFICIENT')",
            name="ck_qtf_run_parameter_result_effect_status_valid",
        ),
        sa.CheckConstraint(
            "length(result_hash) = 64 and result_hash = lower(result_hash)",
            name="ck_qtf_run_parameter_result_hash_shape",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["qtf.experiment_run.id"],
            name="fk_qtf_run_parameter_result_run_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_qtf_run_parameter_result"),
        sa.UniqueConstraint(
            "result_key",
            name="uq_qtf_run_parameter_result_result_key",
        ),
        sa.UniqueConstraint(
            "run_id",
            "parameter_set_key",
            name="uq_qtf_run_parameter_result_run_parameter",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "idx_qtf_run_parameter_result_run_status",
        "run_parameter_result",
        ["run_id", "effect_status"],
        schema=_SCHEMA,
    )

    op.create_table(
        "sector_signal_event",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("parameter_set_key", sa.String(length=96), nullable=False),
        sa.Column("signal_trade_date", sa.Date(), nullable=False),
        sa.Column("sector_code", sa.String(length=32), nullable=False),
        sa.Column("parent_sector_code", sa.String(length=32), nullable=False),
        sa.Column("sector_level", sa.Integer(), nullable=False),
        sa.Column("entry_type", sa.String(length=16), nullable=False),
        sa.Column("signal_state_json", sa.JSON(), nullable=False),
        sa.Column("signal_rank_pct", sa.Numeric(precision=10, scale=6), nullable=False),
        sa.Column("future_outcomes_json", sa.JSON(), nullable=False),
        sa.Column("input_completeness_json", sa.JSON(), nullable=False),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("sector_level = 2", name="ck_qtf_sector_signal_event_level_two"),
        sa.CheckConstraint(
            "entry_type in ('ENTRY', 'RETENTION')",
            name="ck_qtf_sector_signal_event_entry_type_valid",
        ),
        sa.CheckConstraint(
            "signal_rank_pct >= 0 and signal_rank_pct <= 100",
            name="ck_qtf_sector_signal_event_rank_valid",
        ),
        sa.CheckConstraint(
            "length(event_hash) = 64 and event_hash = lower(event_hash)",
            name="ck_qtf_sector_signal_event_hash_shape",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["qtf.experiment_run.id"],
            name="fk_qtf_sector_signal_event_run_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_qtf_sector_signal_event"),
        sa.UniqueConstraint(
            "run_id",
            "parameter_set_key",
            "signal_trade_date",
            "sector_code",
            "entry_type",
            name="uq_qtf_sector_signal_event_identity",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "idx_qtf_sector_signal_event_run_date",
        "sector_signal_event",
        ["run_id", "signal_trade_date", "sector_code"],
        schema=_SCHEMA,
    )

    op.create_table(
        "run_conclusion",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("request_key", sa.String(length=96), nullable=False),
        sa.Column("conclusion", sa.String(length=16), nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("concluded_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "conclusion in ('ENDED', 'OBSERVED')",
            name="ck_qtf_run_conclusion_kind_valid",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["qtf.experiment_run.id"],
            name="fk_qtf_run_conclusion_run_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_qtf_run_conclusion"),
        sa.UniqueConstraint("run_id", name="uq_qtf_run_conclusion_run"),
        sa.UniqueConstraint(
            "request_key",
            name="uq_qtf_run_conclusion_request_key",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "idx_qtf_run_conclusion_concluded",
        "run_conclusion",
        ["concluded_at"],
        schema=_SCHEMA,
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.drop_index(
        "idx_qtf_run_conclusion_concluded",
        table_name="run_conclusion",
        schema=_SCHEMA,
    )
    op.drop_table("run_conclusion", schema=_SCHEMA)
    op.drop_index(
        "idx_qtf_sector_signal_event_run_date",
        table_name="sector_signal_event",
        schema=_SCHEMA,
    )
    op.drop_table("sector_signal_event", schema=_SCHEMA)
    op.drop_index(
        "idx_qtf_run_parameter_result_run_status",
        table_name="run_parameter_result",
        schema=_SCHEMA,
    )
    op.drop_table("run_parameter_result", schema=_SCHEMA)
    op.drop_index(
        "idx_qtf_run_gate_result_run",
        table_name="run_gate_result",
        schema=_SCHEMA,
    )
    op.drop_table("run_gate_result", schema=_SCHEMA)
