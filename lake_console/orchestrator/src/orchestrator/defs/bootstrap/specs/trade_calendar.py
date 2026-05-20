from pathlib import Path

from orchestrator.defs.bootstrap import BootstrapDatasetSpec
from orchestrator.defs.duckdb_sql import (
    TRADE_CALENDAR_BOOTSTRAP_SELECT_TEMPLATE,
    TRADE_CALENDAR_RAW_REQUIRED_COLUMNS,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, RAW, raw_trade_calendar_path


OLD_TUSHARE_LAKE_ROOT = Path("/Volumes/datasource/goldenshare-tushare-lake")


def trade_calendar_bootstrap_spec(
    lake_root: Path | None = None,
    old_lake_root: Path = OLD_TUSHARE_LAKE_ROOT,
) -> BootstrapDatasetSpec:
    target_root = Path(lake_root or DEFAULT_LAKE_ROOT)
    return BootstrapDatasetSpec(
        dataset_key="raw_tushare_trade_calendar",
        layer=RAW,
        old_lake_path_pattern=str(
            old_lake_root
            / "raw_tushare"
            / "trade_cal"
            / "current"
            / "part-000.parquet"
        ),
        target_path_pattern=str(raw_trade_calendar_path(target_root)),
        partition_type="full",
        source_fields=TRADE_CALENDAR_RAW_REQUIRED_COLUMNS,
        target_raw_fields=TRADE_CALENDAR_RAW_REQUIRED_COLUMNS,
        select_sql_template=TRADE_CALENDAR_BOOTSTRAP_SELECT_TEMPLATE,
        empty_policy="require_positive",
        business_key=("exchange", "cal_date"),
    )
