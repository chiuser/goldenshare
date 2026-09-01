import dagster as dg

from orchestrator.defs.ops.gold_stock_daily_trend_channel_repair import (
    gold_stock_daily_trend_channel_repair_op,
)

GOLD_STOCK_DAILY_TREND_CHANNEL_REPAIR_JOB_NAME = (
    "gold_stock_daily_trend_channel_repair_job"
)


@dg.job(
    name=GOLD_STOCK_DAILY_TREND_CHANNEL_REPAIR_JOB_NAME,
    description=(
        "按 qfq factor repair exact batch 修复受影响股票的历史日线趋势通道和 state。"
    ),
)
def gold_stock_daily_trend_channel_repair_job() -> None:
    gold_stock_daily_trend_channel_repair_op()
