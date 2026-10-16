"""Report checks for the new direct-source receipt; no source or Parquet writes."""

from pathlib import Path

import dagster as dg

from orchestrator.defs.io.stock_period_raw import read_json
from orchestrator.defs.paths import DEFAULT_LAKE_STAGING_ROOT
from orchestrator.defs.run_contracts.configs import (
    StockWeeklyBootstrapEventChecksConfig,
)
from orchestrator.defs.run_contracts.stock_period import verify_execution
from orchestrator.defs.stock_period_update import report_file_events


@dg.op(description="按直接源执行receipt补周线物化与检查；不读取旧Prod搬运材料。")
def report_stock_weekly_bootstrap_checks(
    context: dg.OpExecutionContext, config: StockWeeklyBootstrapEventChecksConfig
) -> dict:
    run = Path(DEFAULT_LAKE_STAGING_ROOT) / "stock_period" / "runs" / config.run_id
    manifest = read_json(run / "manifest.json")
    verify_execution(manifest, config.run_id)
    complete = read_json(run / "complete.json")
    count = 0
    for item in complete["files"]:
        if item["freq"] == "week":
            report_file_events(context.instance, item)
            count += 1
    return {"reported_files": count}
