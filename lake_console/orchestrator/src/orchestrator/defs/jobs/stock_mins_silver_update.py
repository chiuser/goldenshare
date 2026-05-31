import dagster as dg

from orchestrator.defs.assets.stk_mins import SILVER_STK_MINS_ASSETS


stock_mins_silver_update_job = dg.define_asset_job(
    name="stock_mins_silver_update_job",
    selection=(
        dg.AssetSelection.assets(*SILVER_STK_MINS_ASSETS)
        | dg.AssetSelection.checks_for_assets(*SILVER_STK_MINS_ASSETS)
    ),
    executor_def=dg.in_process_executor,
    description="按单日分区生成五个股票分钟线 silver 频度资产，不更新 raw/gold。",
)
