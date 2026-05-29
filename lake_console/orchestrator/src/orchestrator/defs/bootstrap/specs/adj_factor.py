from pathlib import Path

from orchestrator.defs.bootstrap import BootstrapDatasetSpec
from orchestrator.defs.duckdb_sql import (
    ADJ_FACTOR_BOOTSTRAP_SELECT_TEMPLATE,
    ADJ_FACTOR_RAW_REQUIRED_COLUMNS,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, RAW, raw_adj_factor_path


OLD_TUSHARE_LAKE_ROOT = Path("/Volumes/datasource/goldenshare-tushare-lake")


def adj_factor_bootstrap_spec(
    lake_root: Path | None = None,
    old_lake_root: Path = OLD_TUSHARE_LAKE_ROOT,
) -> BootstrapDatasetSpec:
    target_root = Path(lake_root or DEFAULT_LAKE_ROOT)
    return BootstrapDatasetSpec(
        dataset_key="raw_tushare_adj_factor",
        layer=RAW,
        old_lake_path_pattern=str(
            old_lake_root
            / "raw_tushare"
            / "adj_factor"
            / "trade_date={partition_key}"
            / "part-000.parquet"
        ),
        target_path_pattern=str(raw_adj_factor_path(target_root, "{partition_key}")),
        partition_type="trade_date",
        source_fields=ADJ_FACTOR_RAW_REQUIRED_COLUMNS,
        target_raw_fields=ADJ_FACTOR_RAW_REQUIRED_COLUMNS,
        select_sql_template=ADJ_FACTOR_BOOTSTRAP_SELECT_TEMPLATE,
        empty_policy="require_positive",
        business_key=("ts_code", "trade_date"),
    )
