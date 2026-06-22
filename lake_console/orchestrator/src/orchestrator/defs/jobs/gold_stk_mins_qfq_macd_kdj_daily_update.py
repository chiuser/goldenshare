import dagster as dg

from orchestrator.defs.assets.stk_mins_qfq_macd_kdj import (
    GOLD_STK_MINS_QFQ_MACD_KDJ_ASSETS,
)
from orchestrator.defs.partitions import cn_a_stock_mins_silver_trade_days


gold_stk_mins_qfq_macd_kdj_daily_update_job = dg.define_asset_job(
    name="gold_stk_mins_qfq_macd_kdj_daily_update_job",
    selection=(
        dg.AssetSelection.assets(*GOLD_STK_MINS_QFQ_MACD_KDJ_ASSETS)
        | dg.AssetSelection.checks_for_assets(*GOLD_STK_MINS_QFQ_MACD_KDJ_ASSETS)
    ),
    executor_def=dg.in_process_executor,
    description="按单日分区生成七频度股票分钟线 qfq MACD/KDJ 指标和 state 资产。",
)


gold_stk_mins_qfq_macd_kdj_check_refresh_job = dg.define_asset_job(
    name="gold_stk_mins_qfq_macd_kdj_check_refresh_job",
    selection=dg.AssetSelection.checks_for_assets(
        *GOLD_STK_MINS_QFQ_MACD_KDJ_ASSETS
    ),
    partitions_def=cn_a_stock_mins_silver_trade_days,
    executor_def=dg.in_process_executor,
    description=(
        "仅刷新七频度股票分钟线 qfq MACD/KDJ 指标和 state 的 asset checks；"
        "不 materialize 资产，不重写 Parquet。"
    ),
)
