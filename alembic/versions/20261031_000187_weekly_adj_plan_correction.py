"""Permit immutable weekly factor corrections; preserve all original records."""

import re

from alembic import op
import sqlalchemy as sa

revision = "20261031_000187"
down_revision = "20261010_000186"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    bind.execute(sa.text("SET LOCAL lock_timeout = '2s'"))
    bind.execute(sa.text("SET LOCAL statement_timeout = '20s'"))
    constraints = sa.inspect(bind).get_check_constraints(
        "stock_weekly_adj_delivery", schema="core"
    )
    kinds = {"plan", "unit", "batch_closed", "bootstrap_closed"}
    found = [
        c["name"]
        for c in constraints
        if "record_kind" in c["sqltext"]
        and set(re.findall(r"'([^']*)'", c["sqltext"])) == kinds
    ]
    if len(found) != 1:
        raise RuntimeError("Expected exactly one original weekly delivery kind CHECK")
    op.create_check_constraint(
        op.f("ck_weekly_adj_delivery_kind_v2"),
        "stock_weekly_adj_delivery",
        "record_kind IN ('plan','unit','batch_closed','bootstrap_closed','plan_correction')",
        schema="core",
        postgresql_not_valid=True,
    )
    op.create_check_constraint(
        op.f("ck_weekly_adj_correction_bytes"),
        "stock_weekly_adj_delivery",
        "CASE WHEN record_kind = 'plan_correction' THEN octet_length(payload::text) <= 1048576 ELSE TRUE END",
        schema="core",
        postgresql_not_valid=True,
    )
    for name in ("ck_weekly_adj_delivery_kind_v2", "ck_weekly_adj_correction_bytes"):
        op.execute(
            f"ALTER TABLE core.stock_weekly_adj_delivery VALIDATE CONSTRAINT {name}"
        )
    op.drop_constraint(
        op.f(found[0]), "stock_weekly_adj_delivery", schema="core", type_="check"
    )


def downgrade():
    raise RuntimeError(
        "Removing approved corrections requires a separately reviewed operation"
    )
