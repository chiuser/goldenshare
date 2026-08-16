"""drop redundant price from equity qfq nineturn daily serving

Revision ID: 20260816_000137
Revises: 20260814_000136
Create Date: 2026-08-16
"""

from __future__ import annotations

from alembic import op


revision = "20260816_000137"
down_revision = "20260814_000136"
branch_labels = None
depends_on = None

_SCHEMA = "core_serving"
_TABLE = "equity_qfq_nineturn_daily"
_CLOSE_CONSTRAINT = "ck_equity_qfq_nineturn_daily_close_positive"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.drop_constraint(
        op.f(_CLOSE_CONSTRAINT),
        _TABLE,
        schema=_SCHEMA,
        type_="check",
    )
    op.drop_column(_TABLE, "close_qfq", schema=_SCHEMA)


def downgrade() -> None:
    raise RuntimeError(
        "股票日线九转价格字段已从正式合同删除，禁止 downgrade 重新引入。"
    )
