"""Switch an explicitly emptied announcement table to exact-source retention.

No business rows are deleted by this migration. Existing hashes have different
semantics; operator-approved reset/reload precedes this schema switch. No backup is required.
"""
from alembic import op

revision = '20261002_000183'
down_revision = '20261002_000182'
branch_labels = depends_on = None


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("SET LOCAL statement_timeout = '25s'")
    op.execute('LOCK TABLE raw_tushare.anns_d IN ACCESS EXCLUSIVE MODE')
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM raw_tushare.anns_d LIMIT 1) THEN
            RAISE EXCEPTION 'anns_d must be empty after an explicitly approved reset; migration will not delete data';
        END IF;
    END $$""")
    op.execute('DROP INDEX IF EXISTS raw_tushare.idx_raw_tushare_anns_d_group_key')
    op.execute('ALTER TABLE raw_tushare.anns_d DROP COLUMN group_key')
    for field in ('ann_date', 'ts_code', 'title'):
        op.execute(f'ALTER TABLE raw_tushare.anns_d ALTER COLUMN {field} DROP NOT NULL')
    op.execute('ALTER TABLE raw_tushare.anns_d ALTER COLUMN raw_payload SET NOT NULL')


def downgrade():
    raise RuntimeError('Exact-source records cannot be converted to the retired dominance contract automatically')
