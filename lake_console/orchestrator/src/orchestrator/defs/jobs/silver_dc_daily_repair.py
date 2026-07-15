"""Job that publishes bounded ``silver_dc_daily`` repair batches."""

import dagster as dg

from orchestrator.defs.ops.silver_dc_daily_repair import silver_dc_daily_repair_op


SILVER_DC_DAILY_REPAIR_JOB_NAME = "silver_dc_daily_repair_job"


@dg.job(
    name=SILVER_DC_DAILY_REPAIR_JOB_NAME,
    executor_def=dg.in_process_executor,
    description="从 Raw 重建有界 silver_dc_daily，并发布 ready repair batch tags。",
)
def silver_dc_daily_repair_job() -> None:
    silver_dc_daily_repair_op()


__all__ = ["SILVER_DC_DAILY_REPAIR_JOB_NAME", "silver_dc_daily_repair_job"]
