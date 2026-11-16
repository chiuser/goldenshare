"""Immutable business plans and unit commits for stock adjusted week/month bars."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '20261116_000189'
down_revision = '20261112_000188'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('stock_period_adj_delivery',
        sa.Column('revision', sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column('contract_version', sa.SmallInteger(), nullable=False),
        sa.Column('batch_id', sa.Uuid(), nullable=False),
        sa.Column('intent_key', sa.Text(), nullable=False),
        sa.Column('record_kind', sa.String(24), nullable=False),
        sa.Column('unit_id', sa.String(128), nullable=False),
        sa.Column('purpose', sa.String(40), nullable=False),
        sa.Column('freq', sa.String(8), nullable=False),
        sa.Column('business_date', sa.Date()), sa.Column('period_date', sa.Date()),
        sa.Column('ts_code', sa.String(16)),
        sa.Column('contract_digest', sa.String(64), nullable=False),
        sa.Column('scope_digest', sa.String(64), nullable=False),
        sa.Column('payload', JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('batch_id','record_kind','unit_id',name='uq_stock_period_adj_delivery_unit'),
        sa.CheckConstraint("record_kind IN ('plan_unit','plan_frozen','unit','batch_closed')", name='stock_period_adj_kind'),
        sa.CheckConstraint("freq IN ('week','month') AND contract_version=1", name='stock_period_adj_contract'),
        schema='core')
    op.create_index('uq_stock_period_adj_frozen_intent','stock_period_adj_delivery',['intent_key'],unique=True,
                    schema='core',postgresql_where=sa.text("record_kind='plan_frozen'"))
    op.create_index('idx_stock_period_adj_business_date','stock_period_adj_delivery',
                    ['purpose','freq','business_date','record_kind'],schema='core')
    op.create_index('idx_stock_period_adj_period_date','stock_period_adj_delivery',
                    ['freq','period_date','record_kind'],schema='core')
    op.execute("""CREATE FUNCTION core.reject_stock_period_adj_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'stock_period_adj_delivery is append only'; END; $$""")
    op.execute("""CREATE TRIGGER stock_period_adj_immutable BEFORE UPDATE OR DELETE ON core.stock_period_adj_delivery
        FOR EACH ROW EXECUTE FUNCTION core.reject_stock_period_adj_mutation()""")


def downgrade():
    raise RuntimeError('不可删除股票复权周/月线的不可变业务记录；恢复须按明确范围处理')
