"""Op-based Dagster job for bounded Gold board technical repairs."""

import dagster as dg

from orchestrator.defs.ops.dc_daily_technical_repair import (
    gold_dc_daily_technical_repair_op,
)


GOLD_DC_DAILY_TECHNICAL_REPAIR_JOB_NAME = "gold_dc_daily_technical_repair_job"


@dg.job(
    name=GOLD_DC_DAILY_TECHNICAL_REPAIR_JOB_NAME,
    executor_def=dg.in_process_executor,
    description=(
        "按 Silver repair batch 有界重算 dc_daily 技术指标，并为每个日期写入可归因事件。"
    ),
)
def gold_dc_daily_technical_repair_job() -> None:
    gold_dc_daily_technical_repair_op()


__all__ = [
    "GOLD_DC_DAILY_TECHNICAL_REPAIR_JOB_NAME",
    "gold_dc_daily_technical_repair_job",
]
