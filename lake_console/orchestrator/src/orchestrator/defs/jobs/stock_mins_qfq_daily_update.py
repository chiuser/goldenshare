import dagster as dg

from orchestrator.defs.assets.stk_mins import GOLD_STK_MINS_QFQ_ASSETS


stock_mins_qfq_daily_update_job = dg.define_asset_job(
    name="stock_mins_qfq_daily_update_job",
    selection=(
        dg.AssetSelection.assets(*GOLD_STK_MINS_QFQ_ASSETS)
        | dg.AssetSelection.checks_for_assets(*GOLD_STK_MINS_QFQ_ASSETS)
    ),
    executor_def=dg.in_process_executor,
    description="按单日分区生成五个股票分钟线 gold qfq 频度资产，不更新 raw/silver。",
)
