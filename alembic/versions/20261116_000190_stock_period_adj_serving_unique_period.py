"""Cycle uniqueness, applied only after the approved existing-row republication."""

from alembic import op

revision = '20261116_000190'
down_revision = '20261116_000189'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE UNIQUE INDEX uq_stk_period_adj_serving_week ON core_serving.stk_period_bar_adj
        (ts_code, (trade_date - (EXTRACT(ISODOW FROM trade_date)::integer - 1))) WHERE freq='week'""")
    op.execute("""CREATE UNIQUE INDEX uq_stk_period_adj_serving_month ON core_serving.stk_period_bar_adj
        (ts_code, (trade_date - (EXTRACT(DAY FROM trade_date)::integer - 1))) WHERE freq='month'""")


def downgrade():
    op.drop_index('uq_stk_period_adj_serving_month', table_name='stk_period_bar_adj', schema='core_serving')
    op.drop_index('uq_stk_period_adj_serving_week', table_name='stk_period_bar_adj', schema='core_serving')
