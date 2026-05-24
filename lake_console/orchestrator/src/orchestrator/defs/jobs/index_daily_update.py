import dagster as dg

from orchestrator.defs.assets.index_daily import raw_tushare_index_daily, silver_index_daily


SILVER_INDEX_DAILY_ACTIVE_POOL_COVERAGE_CHECK_KEY = dg.AssetCheckKey(
    dg.AssetKey("silver_index_daily"),
    "silver_index_daily_active_pool_coverage",
)


index_daily_update_job = dg.define_asset_job(
    name="index_daily_update_job",
    selection=(
        (
            dg.AssetSelection.assets(raw_tushare_index_daily, silver_index_daily)
            | dg.AssetSelection.checks_for_assets(raw_tushare_index_daily, silver_index_daily)
        )
        - dg.AssetSelection.checks(SILVER_INDEX_DAILY_ACTIVE_POOL_COVERAGE_CHECK_KEY)
    ),
    description="更新指数日线原始表和标准表。",
)
