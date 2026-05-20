from pathlib import Path

from orchestrator.defs.bootstrap import BootstrapDatasetSpec
from orchestrator.defs.duckdb_sql import (
    SUSPEND_D_BOOTSTRAP_SELECT_TEMPLATE,
    SUSPEND_D_RAW_COLUMNS,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, RAW, raw_suspend_d_path


OLD_TUSHARE_LAKE_ROOT = Path("/Volumes/datasource/goldenshare-tushare-lake")


def suspend_d_bootstrap_spec(
    lake_root: Path | None = None,
    old_lake_root: Path = OLD_TUSHARE_LAKE_ROOT,
) -> BootstrapDatasetSpec:
    target_root = Path(lake_root or DEFAULT_LAKE_ROOT)
    return BootstrapDatasetSpec(
        dataset_key="raw_tushare_suspend_d",
        layer=RAW,
        old_lake_path_pattern=str(
            old_lake_root
            / "raw_tushare"
            / "suspend_d"
            / "trade_date={partition_key}"
            / "part-000.parquet"
        ),
        target_path_pattern=str(raw_suspend_d_path(target_root, "{partition_key}")),
        partition_type="trade_date",
        source_fields=SUSPEND_D_RAW_COLUMNS,
        target_raw_fields=SUSPEND_D_RAW_COLUMNS,
        select_sql_template=SUSPEND_D_BOOTSTRAP_SELECT_TEMPLATE,
        empty_policy="allow_empty",
        business_key=("ts_code", "trade_date", "suspend_type", "suspend_timing"),
    )
