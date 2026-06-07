import dagster as dg

from orchestrator.defs.assets.stk_mins_qfq_macd_kdj import (
    GOLD_STK_MINS_QFQ_MACD_KDJ_ASSETS,
)


gold_stk_mins_qfq_macd_kdj_daily_update_job = dg.define_asset_job(
    name="gold_stk_mins_qfq_macd_kdj_daily_update_job",
    selection=(
        dg.AssetSelection.assets(*GOLD_STK_MINS_QFQ_MACD_KDJ_ASSETS)
        | dg.AssetSelection.checks_for_assets(*GOLD_STK_MINS_QFQ_MACD_KDJ_ASSETS)
    ),
    executor_def=dg.in_process_executor,
    description="按单日分区生成七频度股票分钟线 qfq MACD/KDJ 指标和 state 资产。",
)
