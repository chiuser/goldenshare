"""add fina indicator dataset on cold HDD storage

Revision ID: 20260829_000160
Revises: 20260829_000159
Create Date: 2026-08-29
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260829_000160"
down_revision = "20260829_000159"
branch_labels = None
depends_on = None


_TABLESPACE = "gs_raw_cold_hdd"
_DECIMAL_FIELDS = (
    "eps",
    "dt_eps",
    "total_revenue_ps",
    "revenue_ps",
    "capital_rese_ps",
    "surplus_rese_ps",
    "undist_profit_ps",
    "extra_item",
    "profit_dedt",
    "gross_margin",
    "current_ratio",
    "quick_ratio",
    "cash_ratio",
    "invturn_days",
    "arturn_days",
    "inv_turn",
    "ar_turn",
    "ca_turn",
    "fa_turn",
    "assets_turn",
    "op_income",
    "valuechange_income",
    "interst_income",
    "daa",
    "ebit",
    "ebitda",
    "fcff",
    "fcfe",
    "current_exint",
    "noncurrent_exint",
    "interestdebt",
    "netdebt",
    "tangible_asset",
    "working_capital",
    "networking_capital",
    "invest_capital",
    "retained_earnings",
    "diluted2_eps",
    "bps",
    "ocfps",
    "retainedps",
    "cfps",
    "ebit_ps",
    "fcff_ps",
    "fcfe_ps",
    "netprofit_margin",
    "grossprofit_margin",
    "cogs_of_sales",
    "expense_of_sales",
    "profit_to_gr",
    "saleexp_to_gr",
    "adminexp_of_gr",
    "finaexp_of_gr",
    "impai_ttm",
    "gc_of_gr",
    "op_of_gr",
    "ebit_of_gr",
    "roe",
    "roe_waa",
    "roe_dt",
    "roa",
    "npta",
    "roic",
    "roe_yearly",
    "roa2_yearly",
    "roe_avg",
    "opincome_of_ebt",
    "investincome_of_ebt",
    "n_op_profit_of_ebt",
    "tax_to_ebt",
    "dtprofit_to_profit",
    "salescash_to_or",
    "ocf_to_or",
    "ocf_to_opincome",
    "capitalized_to_da",
    "debt_to_assets",
    "assets_to_eqt",
    "dp_assets_to_eqt",
    "ca_to_assets",
    "nca_to_assets",
    "tbassets_to_totalassets",
    "int_to_talcap",
    "eqt_to_talcapital",
    "currentdebt_to_debt",
    "longdeb_to_debt",
    "ocf_to_shortdebt",
    "debt_to_eqt",
    "eqt_to_debt",
    "eqt_to_interestdebt",
    "tangibleasset_to_debt",
    "tangasset_to_intdebt",
    "tangibleasset_to_netdebt",
    "ocf_to_debt",
    "ocf_to_interestdebt",
    "ocf_to_netdebt",
    "ebit_to_interest",
    "longdebt_to_workingcapital",
    "ebitda_to_debt",
    "turn_days",
    "roa_yearly",
    "roa_dp",
    "fixed_assets",
    "profit_prefin_exp",
    "non_op_profit",
    "op_to_ebt",
    "nop_to_ebt",
    "ocf_to_profit",
    "cash_to_liqdebt",
    "cash_to_liqdebt_withinterest",
    "op_to_liqdebt",
    "op_to_debt",
    "roic_yearly",
    "total_fa_trun",
    "profit_to_op",
    "q_opincome",
    "q_investincome",
    "q_dtprofit",
    "q_eps",
    "q_netprofit_margin",
    "q_gsprofit_margin",
    "q_exp_to_sales",
    "q_profit_to_gr",
    "q_saleexp_to_gr",
    "q_adminexp_to_gr",
    "q_finaexp_to_gr",
    "q_impair_to_gr_ttm",
    "q_gc_to_gr",
    "q_op_to_gr",
    "q_roe",
    "q_dt_roe",
    "q_npta",
    "q_opincome_to_ebt",
    "q_investincome_to_ebt",
    "q_dtprofit_to_profit",
    "q_salescash_to_or",
    "q_ocf_to_sales",
    "q_ocf_to_or",
    "basic_eps_yoy",
    "dt_eps_yoy",
    "cfps_yoy",
    "op_yoy",
    "ebt_yoy",
    "netprofit_yoy",
    "dt_netprofit_yoy",
    "ocf_yoy",
    "roe_yoy",
    "bps_yoy",
    "assets_yoy",
    "eqt_yoy",
    "tr_yoy",
    "or_yoy",
    "q_gr_yoy",
    "q_gr_qoq",
    "q_sales_yoy",
    "q_sales_qoq",
    "q_op_yoy",
    "q_op_qoq",
    "q_profit_yoy",
    "q_profit_qoq",
    "q_netprofit_yoy",
    "q_netprofit_qoq",
    "equity_yoy",
    "rd_exp",
)
_VIEW_COLUMNS = (
    "ts_code",
    "ann_date",
    "end_date",
    *_DECIMAL_FIELDS,
    "update_flag",
    "source_content_hash",
    "api_name",
    "fetched_at",
)


def _assert_postgresql() -> None:
    dialect_name = op.get_bind().dialect.name
    if dialect_name != "postgresql":
        raise RuntimeError("财务指标 HDD migration 只允许在 PostgreSQL 执行")


def _assert_hdd_tablespace() -> None:
    exists = op.get_bind().execute(
        sa.text("SELECT 1 FROM pg_tablespace WHERE spcname = :name"),
        {"name": _TABLESPACE},
    ).scalar()
    if not exists:
        raise RuntimeError(f"财务指标要求 PostgreSQL tablespace `{_TABLESPACE}`，禁止回退到默认 SSD")


def upgrade() -> None:
    _assert_postgresql()
    _assert_hdd_tablespace()

    op.execute("CREATE SCHEMA IF NOT EXISTS raw_tushare")
    op.execute("CREATE SCHEMA IF NOT EXISTS core_serving")
    op.create_table(
        "fina_indicator",
        sa.Column("ts_code", sa.String(length=16), nullable=False),
        sa.Column("ann_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        *(sa.Column(field_name, sa.Numeric(), nullable=True) for field_name in _DECIMAL_FIELDS),
        sa.Column("update_flag", sa.String(length=8), nullable=False),
        sa.Column("source_content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "api_name",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'fina_indicator_vip'"),
        ),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint(
            "ts_code",
            "ann_date",
            "end_date",
            "update_flag",
            name="pk_raw_tushare_fina_indicator",
        ),
        schema="raw_tushare",
        postgresql_tablespace=_TABLESPACE,
    )
    op.execute(
        "ALTER INDEX raw_tushare.pk_raw_tushare_fina_indicator "
        "SET TABLESPACE gs_raw_cold_hdd"
    )
    op.execute(
        "CREATE INDEX idx_raw_tushare_fina_indicator_ann_date_ts_code "
        "ON raw_tushare.fina_indicator (ann_date, ts_code) "
        "TABLESPACE gs_raw_cold_hdd"
    )
    op.execute(
        "CREATE INDEX idx_raw_tushare_fina_indicator_ts_code_end_ann_update "
        "ON raw_tushare.fina_indicator (ts_code, end_date DESC, ann_date DESC, update_flag) "
        "TABLESPACE gs_raw_cold_hdd"
    )

    selected_columns = ",\n            ".join(_VIEW_COLUMNS)
    op.execute(
        f"""
        CREATE VIEW core_serving.equity_fina_indicator AS
        SELECT
            {selected_columns}
        FROM raw_tushare.fina_indicator
        """
    )


def downgrade() -> None:
    raise RuntimeError("财务指标表保存业务事实，不支持自动 downgrade 删除数据。")
