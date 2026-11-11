"""Execute the configured frequency's retirement cleanup."""

import dagster as dg

from orchestrator.defs.run_contracts.stock_period_retirement_cleanup import (
    StockPeriodRetirementCleanupConfig,
)
from orchestrator.defs.stock_period_retirement_cleanup import execute_retirement_cleanup


@dg.op(required_resource_keys={"lake_root"}, out={})
def raw_stock_period_retirement_cleanup_op(
    context, config: StockPeriodRetirementCleanupConfig
):
    yield from execute_retirement_cleanup(context, config)
