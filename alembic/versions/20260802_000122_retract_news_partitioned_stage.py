"""retract empty news partitioned stage

Revision ID: 20260802_000122
Revises: 20260802_000121
Create Date: 2026-08-02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260802_000122"
down_revision = "20260802_000121"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    source_exists = bind.execute(sa.text("SELECT to_regclass('raw_tushare.news') IS NOT NULL")).scalar_one()
    if not source_exists:
        raise RuntimeError("无法撤销新闻分区 stage：缺少原始 raw_tushare.news 表。")

    stage_exists = bind.execute(
        sa.text("SELECT to_regclass('raw_tushare.news_partitioned_stage') IS NOT NULL")
    ).scalar_one()
    if not stage_exists:
        return

    stage_rows = bind.execute(sa.text("SELECT COUNT(*) FROM raw_tushare.news_partitioned_stage")).scalar_one()
    if int(stage_rows) != 0:
        raise RuntimeError("无法撤销新闻分区 stage：stage 非空，禁止删除任何已复制数据。")

    op.execute("DROP TABLE raw_tushare.news_partitioned_stage")


def downgrade() -> None:
    raise RuntimeError("新闻分区 stage 已撤销，禁止通过 downgrade 自动重建。")
