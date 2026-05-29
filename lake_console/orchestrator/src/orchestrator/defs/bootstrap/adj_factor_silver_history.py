import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import dagster as dg

from orchestrator.defs.assets.adj_factor import (
    SilverAdjFactorPartitionWriteResult,
    write_silver_adj_factor_partition,
)
from orchestrator.defs.partitions import cn_a_stock_current_trade_days
from orchestrator.defs.paths import (
    raw_adj_factor_path,
    silver_adj_factor_path,
    silver_stock_basic_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.sensors.readiness import (
    RAW_ADJ_FACTOR_ASSET_KEY,
    RAW_ADJ_FACTOR_CHECKS,
    AssetReadinessSpec,
    asset_readiness_status,
)


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


@dataclass(frozen=True)
class AdjFactorSilverHistoryPlan:
    selected_partition_keys: tuple[str, ...]
    raw_partition_count: int
    registered_partition_count: int | None
    raw_only_partition_keys: tuple[str, ...]
    partition_only_keys: tuple[str, ...]
    raw_not_ready_partition_keys: tuple[str, ...]
    existing_silver_partition_keys: tuple[str, ...]
    planned_write_partition_keys: tuple[str, ...]
    stock_basic_file_path: Path
    stock_basic_exists: bool

    @property
    def planned_write_count(self) -> int:
        return len(self.planned_write_partition_keys)


@dataclass(frozen=True)
class AdjFactorSilverHistoryReport:
    plan: AdjFactorSilverHistoryPlan
    dry_run: bool
    partition_audits: tuple[AdjFactorSilverHistoryPartitionAudit, ...]

    @property
    def generated_partition_keys(self) -> tuple[str, ...]:
        return tuple(
            audit.partition_key
            for audit in self.partition_audits
            if audit.status == GENERATED_STATUS
        )

    @property
    def skipped_existing_partition_keys(self) -> tuple[str, ...]:
        return tuple(
            audit.partition_key
            for audit in self.partition_audits
            if audit.status == SKIPPED_EXISTING_STATUS
        )


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


def discover_adj_factor_silver_partition_keys(lake_root: Path) -> tuple[str, ...]:
    silver_root = lake_root / "silver" / "quote" / "adj_factor"
    if not silver_root.exists():
        return ()

    partition_keys = set()
    for path in silver_root.glob("trade_date=*/part-000.parquet"):
        partition_key = path.parent.name.removeprefix("trade_date=")
        if TRADE_DATE_PARTITION_PATTERN.match(partition_key):
            partition_keys.add(partition_key)
    return tuple(sorted(partition_keys))


def plan_adj_factor_silver_history(
    *,
    lake_root: Path,
    duckdb: DuckDBResource,
    instance: dg.DagsterInstance | None = None,
    partition_keys: Sequence[str] | None = None,
    strict_partition_alignment: bool = True,
    require_raw_ready: bool = True,
    skip_existing: bool = True,
) -> AdjFactorSilverHistoryPlan:
    del duckdb
    raw_partition_keys = set(discover_adj_factor_raw_partition_keys(lake_root))
    registered_partition_keys = (
        set(instance.get_dynamic_partitions(cn_a_stock_current_trade_days.name))
        if instance
        else None
    )

    if partition_keys is None:
        selected_partition_keys = tuple(sorted(raw_partition_keys))
        raw_only_partition_keys = (
            tuple(sorted(raw_partition_keys - registered_partition_keys))
            if registered_partition_keys is not None
            else ()
        )
        partition_only_keys = (
            tuple(sorted(registered_partition_keys - raw_partition_keys))
            if registered_partition_keys is not None
            else ()
        )
    else:
        selected_partition_keys = tuple(sorted(set(partition_keys)))
        invalid_partition_keys = tuple(
            key
            for key in selected_partition_keys
            if not TRADE_DATE_PARTITION_PATTERN.match(key)
        )
        if invalid_partition_keys:
            raise ValueError(f"Invalid trade_date partition keys: {invalid_partition_keys}")
        raw_only_partition_keys = (
            tuple(
                key
                for key in selected_partition_keys
                if registered_partition_keys is not None
                and key not in registered_partition_keys
            )
        )
        partition_only_keys = tuple(
            key for key in selected_partition_keys if key not in raw_partition_keys
        )

    if strict_partition_alignment and (raw_only_partition_keys or partition_only_keys):
        raise ValueError(
            "raw adj_factor partitions and registered cn_a_stock_current_trade_days "
            "partitions are not aligned: "
            f"raw_only={raw_only_partition_keys[:10]}, "
            f"partition_only={partition_only_keys[:10]}"
        )

    raw_not_ready_partition_keys: tuple[str, ...] = ()
    if instance and require_raw_ready:
        raw_readiness_spec = AssetReadinessSpec(
            RAW_ADJ_FACTOR_ASSET_KEY,
            RAW_ADJ_FACTOR_CHECKS,
        )
        raw_not_ready_partition_keys = tuple(
            partition_key
            for partition_key in selected_partition_keys
            if not asset_readiness_status(
                instance,
                raw_readiness_spec,
                partition_key=partition_key,
            ).ready
        )

    existing_silver_partition_keys = tuple(
        partition_key
        for partition_key in selected_partition_keys
        if silver_adj_factor_path(lake_root, partition_key).exists()
    )
    planned_write_partition_keys = tuple(
        partition_key
        for partition_key in selected_partition_keys
        if not skip_existing
        or partition_key not in set(existing_silver_partition_keys)
    )
    return AdjFactorSilverHistoryPlan(
        selected_partition_keys=selected_partition_keys,
        raw_partition_count=len(raw_partition_keys),
        registered_partition_count=(
            len(registered_partition_keys)
            if registered_partition_keys is not None
            else None
        ),
        raw_only_partition_keys=raw_only_partition_keys,
        partition_only_keys=partition_only_keys,
        raw_not_ready_partition_keys=raw_not_ready_partition_keys,
        existing_silver_partition_keys=existing_silver_partition_keys,
        planned_write_partition_keys=planned_write_partition_keys,
        stock_basic_file_path=silver_stock_basic_path(lake_root),
        stock_basic_exists=silver_stock_basic_path(lake_root).exists(),
    )


def report_adj_factor_silver_history(
    *,
    lake_root: Path,
    duckdb: DuckDBResource,
    instance: dg.DagsterInstance | None = None,
    partition_keys: Sequence[str] | None = None,
    dry_run: bool = True,
    strict_partition_alignment: bool = True,
    require_raw_ready: bool = True,
    overwrite: bool = False,
    skip_existing: bool = True,
) -> AdjFactorSilverHistoryReport:
    plan = plan_adj_factor_silver_history(
        lake_root=lake_root,
        duckdb=duckdb,
        instance=instance,
        partition_keys=partition_keys,
        strict_partition_alignment=strict_partition_alignment,
        require_raw_ready=require_raw_ready,
        skip_existing=skip_existing,
    )
    if not plan.stock_basic_exists:
        raise FileNotFoundError(f"Missing silver stock basic file: {plan.stock_basic_file_path}")
    if plan.raw_not_ready_partition_keys:
        raise ValueError(
            "raw_tushare_adj_factor is not ready for silver history generation: "
            f"{plan.raw_not_ready_partition_keys[:10]}"
        )
    if dry_run:
        return AdjFactorSilverHistoryReport(
            plan=plan,
            dry_run=True,
            partition_audits=(),
        )

    audits = write_adj_factor_silver_history(
        lake_root=lake_root,
        duckdb=duckdb,
        partition_keys=plan.selected_partition_keys,
        overwrite=overwrite,
        skip_existing=skip_existing,
    )
    return AdjFactorSilverHistoryReport(
        plan=plan,
        dry_run=False,
        partition_audits=audits,
    )


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
