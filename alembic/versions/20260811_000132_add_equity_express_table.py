"""add equity express immutable fact table

Revision ID: 20260811_000132
Revises: 20260810_000131
Create Date: 2026-08-11
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260811_000132"
down_revision = "20260810_000131"
branch_labels = None
depends_on = None


_TABLESPACE = "gs_raw_cold_hdd"
_SCHEMA = "core_serving"


def _assert_hdd_tablespace() -> None:
    exists = op.get_bind().execute(
        sa.text("SELECT 1 FROM pg_tablespace WHERE spcname = :name"),
        {"name": _TABLESPACE},
    ).scalar()
    if not exists:
        raise RuntimeError(f"业绩快报事实表要求 PostgreSQL tablespace `{_TABLESPACE}`，禁止回退到默认 SSD")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    _assert_hdd_tablespace()
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {_SCHEMA}")
    op.create_table(
        "equity_express",
        sa.Column("source_entity_key", sa.Text(), nullable=False),
        sa.Column("source_content_hash", sa.String(length=64), nullable=False),
        sa.Column("identity_basis", sa.Text(), nullable=False),
        sa.Column("ts_code", sa.Text(), nullable=False),
        sa.Column("ann_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("revenue", sa.Float(), nullable=True),
        sa.Column("operate_profit", sa.Float(), nullable=True),
        sa.Column("total_profit", sa.Float(), nullable=True),
        sa.Column("n_income", sa.Float(), nullable=True),
        sa.Column("total_assets", sa.Float(), nullable=True),
        sa.Column("total_hldr_eqy_exc_min_int", sa.Float(), nullable=True),
        sa.Column("diluted_eps", sa.Float(), nullable=True),
        sa.Column("diluted_roe", sa.Float(), nullable=True),
        sa.Column("yoy_net_profit", sa.Float(), nullable=True),
        sa.Column("bps", sa.Float(), nullable=True),
        sa.Column("yoy_sales", sa.Float(), nullable=True),
        sa.Column("yoy_op", sa.Float(), nullable=True),
        sa.Column("yoy_tp", sa.Float(), nullable=True),
        sa.Column("yoy_dedu_np", sa.Float(), nullable=True),
        sa.Column("yoy_eps", sa.Float(), nullable=True),
        sa.Column("yoy_roe", sa.Float(), nullable=True),
        sa.Column("growth_assets", sa.Float(), nullable=True),
        sa.Column("yoy_equity", sa.Float(), nullable=True),
        sa.Column("growth_bps", sa.Float(), nullable=True),
        sa.Column("or_last_year", sa.Float(), nullable=True),
        sa.Column("op_last_year", sa.Float(), nullable=True),
        sa.Column("tp_last_year", sa.Float(), nullable=True),
        sa.Column("np_last_year", sa.Float(), nullable=True),
        sa.Column("eps_last_year", sa.Float(), nullable=True),
        sa.Column("open_net_assets", sa.Float(), nullable=True),
        sa.Column("open_bps", sa.Float(), nullable=True),
        sa.Column("perf_summary", sa.Text(), nullable=True),
        sa.Column("is_audit", sa.Integer(), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("update_flag", sa.Text(), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("source_entity_key", name="pk_core_serving_equity_express"),
        schema=_SCHEMA,
        postgresql_tablespace=_TABLESPACE,
    )
    op.execute("ALTER INDEX core_serving.pk_core_serving_equity_express SET TABLESPACE gs_raw_cold_hdd")
    op.execute(
        "CREATE INDEX idx_equity_express_ann_date_ts_code "
        "ON core_serving.equity_express (ann_date DESC, ts_code) TABLESPACE gs_raw_cold_hdd"
    )
    op.execute(
        "CREATE INDEX idx_equity_express_ts_code_end_ann "
        "ON core_serving.equity_express (ts_code, end_date DESC, ann_date DESC) TABLESPACE gs_raw_cold_hdd"
    )
    op.execute(
        "CREATE INDEX idx_equity_express_end_date_ts_code "
        "ON core_serving.equity_express (end_date DESC, ts_code) TABLESPACE gs_raw_cold_hdd"
    )


def downgrade() -> None:
    raise RuntimeError("业绩快报表保存不可变源事实，不支持自动 downgrade 删除数据。")
