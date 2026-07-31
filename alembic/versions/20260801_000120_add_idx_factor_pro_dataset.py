"""add idx_factor_pro raw table and serving view

Revision ID: 20260801_000120
Revises: 20260625_000119
Create Date: 2026-08-01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260801_000120"
down_revision = "20260625_000119"
branch_labels = None
depends_on = None


IDX_FACTOR_PRO_VALUE_COLUMNS: tuple[str, ...] = (
    "open", "high", "low", "close", "pre_close", "change", "pct_change", "vol", "amount",
    "asi_bfq", "asit_bfq", "atr_bfq", "bbi_bfq", "bias1_bfq", "bias2_bfq", "bias3_bfq",
    "boll_lower_bfq", "boll_mid_bfq", "boll_upper_bfq", "brar_ar_bfq", "brar_br_bfq", "cci_bfq",
    "cr_bfq", "dfma_dif_bfq", "dfma_difma_bfq", "dmi_adx_bfq", "dmi_adxr_bfq", "dmi_mdi_bfq",
    "dmi_pdi_bfq", "downdays", "updays", "dpo_bfq", "madpo_bfq", "ema_bfq_10", "ema_bfq_20",
    "ema_bfq_250", "ema_bfq_30", "ema_bfq_5", "ema_bfq_60", "ema_bfq_90", "emv_bfq", "maemv_bfq",
    "expma_12_bfq", "expma_50_bfq", "kdj_bfq", "kdj_d_bfq", "kdj_k_bfq", "ktn_down_bfq",
    "ktn_mid_bfq", "ktn_upper_bfq", "lowdays", "topdays", "ma_bfq_10", "ma_bfq_20", "ma_bfq_250",
    "ma_bfq_30", "ma_bfq_5", "ma_bfq_60", "ma_bfq_90", "macd_bfq", "macd_dea_bfq", "macd_dif_bfq",
    "mass_bfq", "ma_mass_bfq", "mfi_bfq", "mtm_bfq", "mtmma_bfq", "obv_bfq", "psy_bfq", "psyma_bfq",
    "roc_bfq", "maroc_bfq", "rsi_bfq_12", "rsi_bfq_24", "rsi_bfq_6", "taq_down_bfq", "taq_mid_bfq",
    "taq_up_bfq", "trix_bfq", "trma_bfq", "vr_bfq", "wr_bfq", "wr1_bfq", "xsii_td1_bfq",
    "xsii_td2_bfq", "xsii_td3_bfq", "xsii_td4_bfq",
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("CREATE SCHEMA IF NOT EXISTS raw_tushare")
    op.execute("CREATE SCHEMA IF NOT EXISTS core_serving")
    op.create_table(
        "idx_factor_pro",
        sa.Column("ts_code", sa.String(length=16), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        *[sa.Column(column_name, sa.Float(53), nullable=True) for column_name in IDX_FACTOR_PRO_VALUE_COLUMNS],
        sa.Column("api_name", sa.String(length=32), nullable=False, server_default=sa.text("'idx_factor_pro'")),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_payload", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("ts_code", "trade_date", name="pk_raw_tushare_idx_factor_pro"),
        schema="raw_tushare",
    )
    op.create_index(
        "idx_raw_tushare_idx_factor_pro_trade_date",
        "idx_factor_pro",
        ["trade_date"],
        schema="raw_tushare",
    )
    projected_columns = ",\n            ".join(("ts_code", "trade_date", *IDX_FACTOR_PRO_VALUE_COLUMNS))
    op.execute(
        f"""
        CREATE VIEW core_serving.index_factor_pro AS
        SELECT
            {projected_columns},
            'tushare'::varchar(32) AS source,
            fetched_at AS created_at,
            fetched_at AS updated_at
        FROM raw_tushare.idx_factor_pro
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP VIEW IF EXISTS core_serving.index_factor_pro")
    op.drop_index(
        "idx_raw_tushare_idx_factor_pro_trade_date",
        table_name="idx_factor_pro",
        schema="raw_tushare",
    )
    op.drop_table("idx_factor_pro", schema="raw_tushare")
