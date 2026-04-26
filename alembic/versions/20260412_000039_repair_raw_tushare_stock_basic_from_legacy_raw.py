"""repair raw_tushare stock_basic from legacy raw schema"""

from __future__ import annotations

from alembic import op


revision = "20260412_000039"
down_revision = "20260412_000038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO raw_tushare.stock_basic (
            ts_code,
            symbol,
            name,
            area,
            industry,
            fullname,
            enname,
            cnspell,
            exchange,
            curr_type,
            list_status,
            list_date,
            delist_date,
            is_hs,
            act_name,
            act_ent_type,
            api_name,
            fetched_at,
            raw_payload
        )
        SELECT
            ts_code,
            symbol,
            name,
            area,
            industry,
            fullname,
            enname,
            cnspell,
            exchange,
            curr_type,
            list_status,
            list_date,
            delist_date,
            is_hs,
            act_name,
            act_ent_type,
            api_name,
            fetched_at,
            raw_payload
        FROM raw.stock_basic
        ON CONFLICT (ts_code) DO UPDATE
        SET
            symbol = EXCLUDED.symbol,
            name = EXCLUDED.name,
            area = EXCLUDED.area,
            industry = EXCLUDED.industry,
            fullname = EXCLUDED.fullname,
            enname = EXCLUDED.enname,
            cnspell = EXCLUDED.cnspell,
            exchange = EXCLUDED.exchange,
            curr_type = EXCLUDED.curr_type,
            list_status = EXCLUDED.list_status,
            list_date = EXCLUDED.list_date,
            delist_date = EXCLUDED.delist_date,
            is_hs = EXCLUDED.is_hs,
            act_name = EXCLUDED.act_name,
            act_ent_type = EXCLUDED.act_ent_type,
            api_name = EXCLUDED.api_name,
            fetched_at = EXCLUDED.fetched_at,
            raw_payload = EXCLUDED.raw_payload;
        """
    )


def downgrade() -> None:
    # Keep migrated history data during downgrade to avoid accidental data loss.
    pass
