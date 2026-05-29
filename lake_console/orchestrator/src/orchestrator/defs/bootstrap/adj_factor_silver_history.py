import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from orchestrator.defs.assets.adj_factor import (
    SilverAdjFactorPartitionWriteResult,
    write_silver_adj_factor_partition,
)
from orchestrator.defs.paths import raw_adj_factor_path, silver_adj_factor_path
from orchestrator.defs.resources import DuckDBResource


TRADE_DATE_PARTITION_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
GENERATED_STATUS = "generated"
SKIPPED_EXISTING_STATUS = "skipped_existing"


@dataclass(frozen=True)
class AdjFactorSilverHistoryPartitionAudit:
    partition_key: str
    status: str
    raw_file_path: Path
    silver_file_path: Path
    source_row_count: int | None
    selected_row_count: int | None
    rejected_row_count: int | None
    observed_columns: tuple[str, ...]


def discover_adj_factor_raw_partition_keys(lake_root: Path) -> tuple[str, ...]:
    raw_root = lake_root / "raw" / "tushare" / "adj_factor"
    if not raw_root.exists():
        return ()

    partition_keys = set()
    for path in raw_root.glob("trade_date=*/part-000.parquet"):
        partition_key = path.parent.name.removeprefix("trade_date=")
        if TRADE_DATE_PARTITION_PATTERN.match(partition_key):
            partition_keys.add(partition_key)
    return tuple(sorted(partition_keys))


def write_adj_factor_silver_history_partition(
    *,
    lake_root: Path,
    duckdb: DuckDBResource,
    partition_key: str,
    overwrite: bool = False,
) -> AdjFactorSilverHistoryPartitionAudit:
    if not TRADE_DATE_PARTITION_PATTERN.match(partition_key):
        raise ValueError(f"Invalid trade_date partition key: {partition_key}")

    write_result = write_silver_adj_factor_partition(
        lake_root=lake_root,
        duckdb=duckdb,
        partition_key=partition_key,
        overwrite=overwrite,
    )
    return _generated_audit(partition_key, write_result)


def write_adj_factor_silver_history(
    *,
    lake_root: Path,
    duckdb: DuckDBResource,
    partition_keys: Sequence[str] | None = None,
    overwrite: bool = False,
    skip_existing: bool = True,
) -> tuple[AdjFactorSilverHistoryPartitionAudit, ...]:
    selected_partition_keys = tuple(
        partition_keys
        if partition_keys is not None
        else discover_adj_factor_raw_partition_keys(lake_root)
    )
    audits = []
    for partition_key in selected_partition_keys:
        if not TRADE_DATE_PARTITION_PATTERN.match(partition_key):
            raise ValueError(f"Invalid trade_date partition key: {partition_key}")

        silver_path = silver_adj_factor_path(lake_root, partition_key)
        if silver_path.exists() and not overwrite and skip_existing:
            audits.append(_skipped_existing_audit(lake_root, partition_key))
            continue

        audits.append(
            write_adj_factor_silver_history_partition(
                lake_root=lake_root,
                duckdb=duckdb,
                partition_key=partition_key,
                overwrite=overwrite,
            )
        )
    return tuple(audits)


def _generated_audit(
    partition_key: str,
    write_result: SilverAdjFactorPartitionWriteResult,
) -> AdjFactorSilverHistoryPartitionAudit:
    return AdjFactorSilverHistoryPartitionAudit(
        partition_key=partition_key,
        status=GENERATED_STATUS,
        raw_file_path=write_result.raw_file_path,
        silver_file_path=write_result.silver_file_path,
        source_row_count=write_result.source_row_count,
        selected_row_count=write_result.selected_row_count,
        rejected_row_count=write_result.rejected_row_count,
        observed_columns=write_result.observed_columns,
    )


def _skipped_existing_audit(
    lake_root: Path,
    partition_key: str,
) -> AdjFactorSilverHistoryPartitionAudit:
    return AdjFactorSilverHistoryPartitionAudit(
        partition_key=partition_key,
        status=SKIPPED_EXISTING_STATUS,
        raw_file_path=raw_adj_factor_path(lake_root, partition_key),
        silver_file_path=silver_adj_factor_path(lake_root, partition_key),
        source_row_count=None,
        selected_row_count=None,
        rejected_row_count=None,
        observed_columns=(),
    )
