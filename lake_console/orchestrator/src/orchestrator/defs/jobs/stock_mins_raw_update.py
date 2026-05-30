import dagster as dg

from orchestrator.defs.assets.stk_mins import RAW_STK_MINS_ASSETS


stock_mins_raw_update_job = dg.define_asset_job(
    name="stock_mins_raw_update_job",
    selection=(
        dg.AssetSelection.assets(*RAW_STK_MINS_ASSETS)
        | dg.AssetSelection.checks_for_assets(*RAW_STK_MINS_ASSETS)
    ),
    executor_def=dg.in_process_executor,
    description="按单日分区更新五个股票分钟线 raw 频度资产，不进入 silver/gold。",
)
