from pathlib import Path

from orchestrator.defs.bootstrap import BootstrapDatasetSpec
from orchestrator.defs.duckdb_sql import (
    STOCK_BASIC_BOOTSTRAP_SELECT_TEMPLATE,
    STOCK_BASIC_RAW_COLUMNS,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, RAW, raw_stock_basic_path


OLD_TUSHARE_LAKE_ROOT = Path("/Volumes/datasource/goldenshare-tushare-lake")


def stock_basic_bootstrap_spec(
    lake_root: Path | None = None,
    old_lake_root: Path = OLD_TUSHARE_LAKE_ROOT,
) -> BootstrapDatasetSpec:
    target_root = Path(lake_root or DEFAULT_LAKE_ROOT)
    return BootstrapDatasetSpec(
        dataset_key="raw_tushare_stock_basic",
        layer=RAW,
        old_lake_path_pattern=str(
            old_lake_root
            / "raw_tushare"
            / "stock_basic"
            / "current"
            / "part-000.parquet"
        ),
        target_path_pattern=str(raw_stock_basic_path(target_root)),
        partition_type="full",
        source_fields=STOCK_BASIC_RAW_COLUMNS,
        target_raw_fields=STOCK_BASIC_RAW_COLUMNS,
        select_sql_template=STOCK_BASIC_BOOTSTRAP_SELECT_TEMPLATE,
        empty_policy="require_positive",
        business_key=("ts_code",),
    )
