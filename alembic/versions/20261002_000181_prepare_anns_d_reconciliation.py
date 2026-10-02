"""Expand announcement schema; identity/data APPLY remains a reviewed P4 action."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261002_000181"
down_revision = "20260916_000180"
branch_labels = depends_on = None


def upgrade():
    op.alter_column('anns_d', 'url', nullable=True, schema='raw_tushare')
    op.alter_column('anns_d', 'rec_time', nullable=True, schema='raw_tushare')
    # NULL during expansion only. P4 APPLY must populate identities then SET NOT NULL.
    op.add_column('anns_d', sa.Column('group_key', sa.String(64), nullable=True), schema='raw_tushare')
    op.create_index('idx_raw_tushare_anns_d_group_key', 'anns_d', ['group_key'], schema='raw_tushare')
    op.create_table('anns_d_identity_migration_header',
                    sa.Column('migration_token', sa.Uuid(), primary_key=True),
                    sa.Column('contract_digest', sa.String(64), nullable=False),
                    sa.Column('high_water_id', sa.BigInteger(), nullable=False),
                    sa.Column('candidate_count', sa.BigInteger(), nullable=False),
                    sa.Column('keep_count', sa.BigInteger(), nullable=False),
                    sa.Column('delete_count', sa.BigInteger(), nullable=False),
                    sa.Column('manifest_digest', sa.String(64), nullable=False),
                    sa.Column('frozen_at', sa.DateTime(timezone=True), nullable=False), schema='raw_tushare')
    op.create_table('anns_d_identity_migration',
                    sa.Column('migration_token', sa.Uuid(), nullable=False),
                    sa.Column('raw_id', sa.BigInteger(), nullable=False),
                    sa.Column('old_hash', sa.String(64), nullable=False),
                    sa.Column('new_hash', sa.String(64), nullable=False),
                    sa.Column('group_key', sa.String(64), nullable=False),
                    sa.Column('action', sa.String(24), nullable=False),
                    sa.Column('survivor_raw_id', sa.BigInteger()),
                    sa.Column('applied_at', sa.DateTime(timezone=True)),
                    sa.PrimaryKeyConstraint('migration_token', 'raw_id'),
                    sa.ForeignKeyConstraint(['migration_token'], ['raw_tushare.anns_d_identity_migration_header.migration_token']),
                    sa.CheckConstraint("action IN ('keep','delete_identical','delete_covered')", name='ck_anns_identity_action'),
                    schema='raw_tushare')
    op.create_index('idx_anns_identity_migration_group', 'anns_d_identity_migration',
                    ['migration_token', 'group_key', 'raw_id'], schema='raw_tushare')


def downgrade():
    # No automatic destructive downgrade once new source rows/mappings have been written.
    raise RuntimeError('公告可空字段与身份迁移须按已审阅恢复方案处理，禁止自动降级删除数据')
