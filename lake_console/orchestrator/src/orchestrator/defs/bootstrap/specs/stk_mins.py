from dataclasses import replace
from pathlib import Path
from typing import Any

from orchestrator.defs.bootstrap import BootstrapDatasetSpec, bootstrap_partition_to_raw
from orchestrator.defs.duckdb_sql import (
    STK_MINS_BOOTSTRAP_SELECT_TEMPLATE,
    STK_MINS_RAW_REQUIRED_COLUMNS,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, RAW, raw_stk_mins_path
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.stk_mins import (
    STK_MINS_FREQS,
    normalize_stk_mins_freq,
)


BACKUP_STK_MINS_ROOT = Path("/Volumes/datasource/backup/research/stk_mins_by_date_clean_next")

STK_MINS_BOOTSTRAP_DATASET_KEYS = {
    1: "raw_stk_mins_1m",
    5: "raw_stk_mins_5m",
    15: "raw_stk_mins_15m",
    30: "raw_stk_mins_30m",
    60: "raw_stk_mins_60m",
}


def stk_mins_bootstrap_spec(
    freq: int | str,
    lake_root: Path | None = None,
    backup_root: Path = BACKUP_STK_MINS_ROOT,
) -> BootstrapDatasetSpec:
    normalized_freq = normalize_stk_mins_freq(freq)
    target_root = Path(lake_root or DEFAULT_LAKE_ROOT)
    return BootstrapDatasetSpec(
        dataset_key=STK_MINS_BOOTSTRAP_DATASET_KEYS[normalized_freq],
        layer=RAW,
        old_lake_path_pattern=str(
            Path(backup_root)
            / f"freq={normalized_freq}"
            / "trade_date={partition_key}"
            / "*.parquet"
        ),
        target_path_pattern=str(
            raw_stk_mins_path(target_root, normalized_freq, "{partition_key}")
        ),
        partition_type="trade_date",
        source_fields=STK_MINS_RAW_REQUIRED_COLUMNS,
        target_raw_fields=STK_MINS_RAW_REQUIRED_COLUMNS,
        select_sql_template=STK_MINS_BOOTSTRAP_SELECT_TEMPLATE,
        empty_policy="require_positive",
        business_key=("ts_code", "trade_time"),
    )


def bootstrap_stk_mins_partition_to_raw(
    spec: BootstrapDatasetSpec,
    partition_key: str,
    duckdb_resource: DuckDBResource,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    if spec.dataset_key not in STK_MINS_BOOTSTRAP_DATASET_KEYS.values():
        raise ValueError(f"Unsupported stk_mins bootstrap spec: {spec.dataset_key}")

    target_path = spec.target_path(partition_key)
    if target_path.exists() and not overwrite:
        raise FileExistsError(f"Target stk_mins raw file already exists: {target_path}")

    source_path = resolve_stk_mins_backup_partition_path(spec, partition_key)
    exact_source_spec = replace(spec, old_lake_path_pattern=str(source_path))
    return bootstrap_partition_to_raw(exact_source_spec, partition_key, duckdb_resource)


def resolve_stk_mins_backup_partition_path(
    spec: BootstrapDatasetSpec,
    partition_key: str,
) -> Path:
    pattern = spec.source_path(partition_key)
    matches = sorted(path for path in pattern.parent.glob(pattern.name) if path.is_file())
    if not matches:
        raise FileNotFoundError(
            "No stk_mins backup parquet file found for "
            f"{spec.dataset_key}[{partition_key}] under {pattern.parent}"
        )
    if len(matches) > 1:
        joined = ", ".join(path.name for path in matches)
        raise ValueError(
            "Expected exactly one stk_mins backup parquet file for "
            f"{spec.dataset_key}[{partition_key}], got {len(matches)}: {joined}"
        )
    return matches[0]


def all_stk_mins_bootstrap_specs(
    lake_root: Path | None = None,
    backup_root: Path = BACKUP_STK_MINS_ROOT,
) -> tuple[BootstrapDatasetSpec, ...]:
    return tuple(
        stk_mins_bootstrap_spec(freq, lake_root=lake_root, backup_root=backup_root)
        for freq in STK_MINS_FREQS
    )
