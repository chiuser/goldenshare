"""rename st source field to st_type

Revision ID: 20260812_000133
Revises: 20260811_000132
Create Date: 2026-08-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260812_000133"
down_revision = "20260811_000132"
branch_labels = None
depends_on = None


def _relation_kind(bind: sa.Connection, relation_name: str) -> str | None:
    return bind.execute(
        sa.text(
            """
            SELECT relkind
            FROM pg_class
            WHERE oid = to_regclass(:relation_name)
            """
        ),
        {"relation_name": relation_name},
    ).scalar_one_or_none()


def _columns(bind: sa.Connection, *, schema: str, table: str) -> set[str]:
    return set(
        bind.execute(
            sa.text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = :schema
                  AND table_name = :table
                """
            ),
            {"schema": schema, "table": table},
        ).scalars()
    )


def _require_old_field_contract(bind: sa.Connection) -> None:
    if _relation_kind(bind, "raw_tushare.st") != "r":
        raise RuntimeError("ST 字段契约迁移要求 raw_tushare.st 为已存在的物理表。")
    if _relation_kind(bind, "core_serving_light.st") != "v":
        raise RuntimeError("ST 字段契约迁移要求 core_serving_light.st 为已存在的普通视图。")

    raw_columns = _columns(bind, schema="raw_tushare", table="st")
    view_columns = _columns(bind, schema="core_serving_light", table="st")
    if "st_tpye" not in raw_columns or "st_type" in raw_columns:
        raise RuntimeError("raw_tushare.st 字段不符合迁移前契约，拒绝猜测重命名。")
    if "st_tpye" not in view_columns or "st_type" in view_columns:
        raise RuntimeError("core_serving_light.st 字段不符合迁移前契约，拒绝猜测重命名。")


def _require_current_field_contract(bind: sa.Connection) -> None:
    raw_columns = _columns(bind, schema="raw_tushare", table="st")
    view_columns = _columns(bind, schema="core_serving_light", table="st")
    if "st_type" not in raw_columns or "st_tpye" in raw_columns:
        raise RuntimeError("raw_tushare.st 未完成 st_type 字段契约收口。")
    if "st_type" not in view_columns or "st_tpye" in view_columns:
        raise RuntimeError("core_serving_light.st 未完成 st_type 字段契约收口。")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    _require_old_field_contract(bind)
    op.alter_column("st", "st_tpye", new_column_name="st_type", schema="raw_tushare")
    op.execute("ALTER VIEW core_serving_light.st RENAME COLUMN st_tpye TO st_type")
    _require_current_field_contract(bind)


def downgrade() -> None:
    raise RuntimeError("ST 源字段事实已收口为 st_type，禁止 downgrade 重新引入已失效字段。")
