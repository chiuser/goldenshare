import dagster as dg

from orchestrator.defs.assets.stk_mins import RAW_STK_MINS_ASSETS
from orchestrator.defs.run_contracts.configs import (
    build_stock_mins_raw_update_job_run_config,
)


stock_mins_raw_update_job = dg.define_asset_job(
    name="stock_mins_raw_update_job",
    selection=(
        dg.AssetSelection.assets(*RAW_STK_MINS_ASSETS)
        | dg.AssetSelection.checks_for_assets(*RAW_STK_MINS_ASSETS)
    ),
    executor_def=dg.in_process_executor,
    description="按单日分区更新五个股票分钟线 raw 频度资产，不进入 silver/gold。",
)

stock_mins_raw_update_from_prod_job = dg.define_asset_job(
    name="stock_mins_raw_update_from_prod_job",
    selection=(
        dg.AssetSelection.assets(*RAW_STK_MINS_ASSETS)
        | dg.AssetSelection.checks_for_assets(*RAW_STK_MINS_ASSETS)
    ),
    config=build_stock_mins_raw_update_job_run_config(source="prod_db"),
    executor_def=dg.in_process_executor,
    description="从 prod DB 只读抽取单日五个股票分钟线 raw 频度资产，不进入 silver/gold。",
)
