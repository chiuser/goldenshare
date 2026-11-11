"""Run the approved factor-change period history workflow."""

import dagster as dg

from orchestrator.defs.run_contracts.stock_period_history_repair import (
    StockPeriodHistoryRepairConfig,
)
from orchestrator.defs.stock_period_history_repair import execute_history_repair


@dg.op(required_resource_keys={"lake_root"}, out={})
def raw_stock_period_history_repair_op(context, config: StockPeriodHistoryRepairConfig):
    yield from execute_history_repair(context, config)
