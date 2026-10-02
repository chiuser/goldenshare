"""Add announcement business receipts; no business rows are modified."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = '20261002_000182'
down_revision = '20261002_000181'
branch_labels = depends_on = None


def upgrade():
    op.create_table('anns_d_sync_unit',
        sa.Column('execution_token', sa.Uuid(), primary_key=True),
        sa.Column('contract_digest', sa.String(64), primary_key=True),
        sa.Column('scope_hash', sa.String(64), primary_key=True),
        sa.Column('ann_date', sa.Date(), primary_key=True),
        sa.Column('attempt_token', sa.Uuid(), nullable=False),
        *[sa.Column(name, sa.BigInteger(), nullable=False) for name in
          ('terminal_page_number', 'terminal_offset', 'terminal_rows', 'rows_observed', 'rows_committed')],
        sa.Column('reason_counts', postgresql.JSONB(), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        schema='raw_tushare')
    op.create_table('anns_d_sync_request_budget',
        sa.Column('execution_token', sa.Uuid(), primary_key=True),
        sa.Column('contract_digest', sa.String(64), nullable=False),
        sa.Column('scope_hash', sa.String(64), nullable=False),
        sa.Column('issued_requests', sa.BigInteger(), nullable=False, server_default=sa.text('0')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        schema='raw_tushare')


def downgrade():
    raise RuntimeError('公告业务凭证/请求预算不允许自动删除，须审阅恢复方案')
