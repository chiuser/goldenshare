import hashlib
import json
import os
import re
import resource
import shutil
import stat
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import date
from pathlib import Path

import dagster as dg

from orchestrator.defs.assets.adj_factor import (
    SilverAdjFactorPartitionWriteResult,
    write_silver_adj_factor_partition,
)
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.duckdb_sql import (
    adj_factor_current_listed_stock_select,
    copy_query_to_parquet,
    duckdb_string,
    read_parquet,
    silver_adj_factor_select,
)
from orchestrator.defs.partitions import cn_a_stock_current_trade_days
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    DEFAULT_LAKE_STAGING_ROOT,
    raw_adj_factor_path,
    silver_adj_factor_path,
    silver_stock_lifecycle_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.sensors.readiness import (
    RAW_ADJ_FACTOR_ASSET_KEY,
    RAW_ADJ_FACTOR_CHECKS,
    AssetReadinessSpec,
    asset_readiness_status,
    silver_stock_lifecycle_ready_for_trade_date,
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
    stock_lifecycle_file_path: Path
    stock_lifecycle_exists: bool

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
        stock_lifecycle_file_path=silver_stock_lifecycle_path(lake_root),
        stock_lifecycle_exists=silver_stock_lifecycle_path(lake_root).exists(),
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
    if not plan.stock_lifecycle_exists:
        raise FileNotFoundError(
            "Missing silver stock lifecycle file: "
            f"{plan.stock_lifecycle_file_path}"
        )
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


# The rebuild is a factor-only manual operation; no ordinary job consumes its plan.
REBUILD_BATCH_DATES = 64
REBUILD_MAX_RSS_BYTES = 1024**3
REBUILD_MAX_CANDIDATE_BYTES = 256 * 1024**2
REBUILD_MIN_FREE_BYTES = 1024**3


class AdjFactorSilverRebuildError(ValueError):
    """Reject an unsafe or drifted factor Silver rebuild."""


@dataclass(frozen=True)
class AdjFactorSilverRebuildBudget:
    batch_dates: int = REBUILD_BATCH_DATES
    duckdb_memory_limit: str = "512MiB"
    threads: int = 2
    max_rss_bytes: int = REBUILD_MAX_RSS_BYTES
    max_candidate_bytes: int = REBUILD_MAX_CANDIDATE_BYTES
    max_spill: str = "512MiB"
    min_free_bytes: int = REBUILD_MIN_FREE_BYTES


@dataclass(frozen=True)
class AdjFactorFileFingerprint:
    path: str
    size: int
    mtime_ns: int
    sha256: str


@dataclass(frozen=True)
class AdjFactorSilverRebuildUnit:
    partition_key: str
    raw: AdjFactorFileFingerprint
    silver: AdjFactorFileFingerprint
    original_rows: int
    expected_rows: int
    removed_rows: int


@dataclass(frozen=True)
class AdjFactorSilverRebuildPlan:
    lake_root: str
    listing_as_of_date: str
    lifecycle: AdjFactorFileFingerprint
    raw_inputs: tuple[AdjFactorFileFingerprint, ...]
    source_code: tuple[AdjFactorFileFingerprint, ...]
    units: tuple[AdjFactorSilverRebuildUnit, ...]
    budget: AdjFactorSilverRebuildBudget = AdjFactorSilverRebuildBudget()
    plan_hash: str = ""


def _rebuild_check_path(path: Path) -> None:
    if not path.is_absolute() or ".." in path.parts:
        raise AdjFactorSilverRebuildError("rebuild_path_invalid")
    if "goldenshare-tushare-lake" in path.parts:
        raise AdjFactorSilverRebuildError("retired_lake_forbidden")
    for parent in (*reversed(path.parents), path):
        if (parent.exists() or parent.is_symlink()) and stat.S_ISLNK(parent.lstat().st_mode):
            raise AdjFactorSilverRebuildError("rebuild_symlink_forbidden")


def _rebuild_check_budget(cancel: Callable[[], None]) -> None:
    cancel()
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if (peak if sys.platform == "darwin" else peak * 1024) > REBUILD_MAX_RSS_BYTES:
        raise AdjFactorSilverRebuildError("rebuild_rss_budget_exceeded")


def _rebuild_fingerprint(path: Path, cancel: Callable[[], None]) -> AdjFactorFileFingerprint:
    _rebuild_check_path(path)
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024**2):
            _rebuild_check_budget(cancel)
            digest.update(block)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise AdjFactorSilverRebuildError("rebuild_input_drift")
    return AdjFactorFileFingerprint(str(path), after.st_size, after.st_mtime_ns, digest.hexdigest())


def _rebuild_assert_identity(identity: AdjFactorFileFingerprint, cancel: Callable[[], None]) -> None:
    if _rebuild_fingerprint(Path(identity.path), cancel) != identity:
        raise AdjFactorSilverRebuildError(f"rebuild_input_drift: {identity.path}")


def _rebuild_settings(temp_directory: Path) -> DuckDBConnectionSettings:
    budget = AdjFactorSilverRebuildBudget()
    return DuckDBConnectionSettings(
        temp_directory=temp_directory, memory_limit=budget.duckdb_memory_limit,
        threads=budget.threads, max_temp_directory_size=budget.max_spill,
    )


def _rebuild_plan_hash(plan: AdjFactorSilverRebuildPlan) -> str:
    payload = asdict(plan)
    payload.pop("plan_hash")
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _rebuild_batch_comparison(connection, raw_paths: Sequence[Path], silver_paths: Sequence[Path],
                              lifecycle_path: Path) -> dict[str, tuple[int, int, int]]:
    raw_quality = " UNION ALL ".join(
        f"SELECT ts_code,try_strptime(trade_date,'%Y%m%d')::DATE trade_date,adj_factor,"
        f"DATE {duckdb_string(path.parent.name.removeprefix('trade_date='))} expected_date "
        f"FROM {read_parquet(path)}" for path in raw_paths
    )
    silver_quality = " UNION ALL ".join(
        f"SELECT ts_code,trade_date,adj_factor,"
        f"DATE {duckdb_string(path.parent.name.removeprefix('trade_date='))} expected_date "
        f"FROM {read_parquet(path)}" for path in silver_paths
    )
    for quality in (raw_quality, silver_quality):
        invalid = connection.execute(f"""WITH factors AS ({quality})
            SELECT (SELECT count(*) FROM factors WHERE ts_code IS NULL OR trim(ts_code)=''
              OR trade_date IS NULL OR trade_date<>expected_date
              OR adj_factor IS NULL OR NOT isfinite(adj_factor) OR adj_factor<=0),
              (SELECT count(*) FROM (SELECT ts_code,trade_date FROM factors
                GROUP BY ts_code,trade_date HAVING count(*)>1))""").fetchone()
        if any(invalid):
            raise AdjFactorSilverRebuildError("rebuild_input_integrity_failed")
    source = " UNION ALL ".join(f"SELECT * FROM {read_parquet(path)}" for path in silver_paths)
    connection.execute(f"CREATE OR REPLACE TEMP VIEW factor_rebuild_before AS {source}")
    connection.execute(
        "CREATE OR REPLACE TEMP VIEW factor_rebuild_expected AS "
        + silver_adj_factor_select(raw_paths, lifecycle_path)
    )
    retained_sql = adj_factor_current_listed_stock_select(lifecycle_path)
    additions, current_removals = connection.execute(f"""
        WITH added AS (SELECT * FROM factor_rebuild_expected EXCEPT ALL SELECT * FROM factor_rebuild_before),
        removed AS (SELECT * FROM factor_rebuild_before EXCEPT ALL SELECT * FROM factor_rebuild_expected)
        SELECT (SELECT count(*) FROM added),
          (SELECT count(*) FROM removed JOIN ({retained_sql}) listed USING(ts_code))
    """).fetchone()
    if additions or current_removals:
        samples = connection.execute(f"""
            WITH added AS (SELECT * FROM factor_rebuild_expected EXCEPT ALL SELECT * FROM factor_rebuild_before),
            removed AS (SELECT * FROM factor_rebuild_before EXCEPT ALL SELECT * FROM factor_rebuild_expected)
            SELECT * FROM added UNION ALL SELECT removed.* FROM removed
            JOIN ({retained_sql}) listed USING(ts_code) ORDER BY ts_code,trade_date LIMIT 5
        """).fetchall()
        raise AdjFactorSilverRebuildError(
            f"rebuild_current_listed_values_differ: additions={additions}, "
            f"current_removals={current_removals}, samples={samples}"
        )
    rows = connection.execute("""
        WITH removed AS (SELECT * FROM factor_rebuild_before EXCEPT ALL SELECT * FROM factor_rebuild_expected),
        counts AS (
          SELECT trade_date, count(*) original_rows, 0::BIGINT expected_rows, 0::BIGINT removed_rows
          FROM factor_rebuild_before GROUP BY trade_date
          UNION ALL SELECT trade_date,0,count(*),0 FROM factor_rebuild_expected GROUP BY trade_date
          UNION ALL SELECT trade_date,0,0,count(*) FROM removed GROUP BY trade_date
        ) SELECT trade_date,sum(original_rows),sum(expected_rows),sum(removed_rows)
          FROM counts GROUP BY trade_date ORDER BY trade_date
    """).fetchall()
    return {str(day): (int(old), int(expected), int(removed)) for day, old, expected, removed in rows}


def plan_silver_adj_factor_rebuild(
    *, lake_root: Path, temp_directory: Path, instance: dg.DagsterInstance,
    listing_as_of_date: str, cancel: Callable[[], None] = lambda: None,
    progress: Callable[[int, int], None] = lambda completed, total: None,
) -> AdjFactorSilverRebuildPlan:
    """Read-only bounded plan for existing Silver; reject changes to any listed value."""
    from orchestrator.defs import assets, duckdb_sql, paths
    from orchestrator.defs.checks import adj_factor_checks

    _rebuild_check_path(lake_root)
    if lake_root != Path(DEFAULT_LAKE_ROOT) and not (
        lake_root.is_relative_to(Path("/private/tmp"))
        or lake_root.is_relative_to(Path("/private/var/folders"))
    ):
        raise AdjFactorSilverRebuildError("rebuild_lake_root_invalid")
    if date.fromisoformat(listing_as_of_date).isoformat() != listing_as_of_date:
        raise AdjFactorSilverRebuildError("rebuild_listing_date_invalid")
    if not silver_stock_lifecycle_ready_for_trade_date(instance, listing_as_of_date).ready:
        raise AdjFactorSilverRebuildError("rebuild_current_listing_not_ready")
    lifecycle = _rebuild_fingerprint(silver_stock_lifecycle_path(lake_root), cancel)
    raw_inputs = tuple(_rebuild_fingerprint(raw_adj_factor_path(lake_root, day), cancel)
                       for day in discover_adj_factor_raw_partition_keys(lake_root))
    raw_by_path = {identity.path: identity for identity in raw_inputs}
    days = discover_adj_factor_silver_partition_keys(lake_root)
    if not days:
        raise AdjFactorSilverRebuildError("rebuild_no_existing_silver")
    identities = [_rebuild_fingerprint(silver_adj_factor_path(lake_root, day), cancel) for day in days]
    units = []
    for offset in range(0, len(days), REBUILD_BATCH_DATES):
        _rebuild_check_budget(cancel)
        selected = days[offset:offset + REBUILD_BATCH_DATES]
        raw = [raw_adj_factor_path(lake_root, day) for day in selected]
        silver = [silver_adj_factor_path(lake_root, day) for day in selected]
        if any(str(path) not in raw_by_path for path in raw):
            raise AdjFactorSilverRebuildError("rebuild_raw_missing")
        with connect_configured_duckdb(_rebuild_settings(temp_directory), temp_policy="existing_no_spill") as connection:
            invalid_lifecycle = connection.execute(f"""SELECT count(*) FROM (
                SELECT ts_code FROM {read_parquet(Path(lifecycle.path))}
                GROUP BY ts_code HAVING ts_code IS NULL OR trim(ts_code)='' OR count(*)<>1
            )""").fetchone()[0]
            if invalid_lifecycle:
                raise AdjFactorSilverRebuildError("rebuild_listing_identity_invalid")
            observed = _rebuild_batch_comparison(connection, raw, silver, Path(lifecycle.path))
            for day, raw_path, silver_path in zip(selected, raw, silver, strict=True):
                for path, schema in ((raw_path, adj_factor_checks.ADJ_FACTOR_RAW_COLUMN_TYPES),
                                     (silver_path, adj_factor_checks.ADJ_FACTOR_SILVER_COLUMN_TYPES)):
                    columns = dict(row[:2] for row in connection.execute(
                        f"DESCRIBE SELECT * FROM {read_parquet(path)}").fetchall())
                    if columns != schema:
                        raise AdjFactorSilverRebuildError("rebuild_schema_invalid")
                if day not in observed or observed[day][1] <= 0:
                    raise AdjFactorSilverRebuildError("rebuild_partition_invalid")
                units.append(AdjFactorSilverRebuildUnit(day, raw_by_path[str(raw_path)],
                    identities[offset + selected.index(day)], *observed[day]))
        progress(min(offset + REBUILD_BATCH_DATES, len(days)), len(days))
    source_code = tuple(_rebuild_fingerprint(Path(module.__file__), cancel)
                        for module in (sys.modules[__name__], duckdb_sql, adj_factor_checks, assets.adj_factor, paths))
    plan = AdjFactorSilverRebuildPlan(str(lake_root), listing_as_of_date, lifecycle,
                                    raw_inputs, source_code, tuple(units))
    plan = replace(plan, plan_hash=_rebuild_plan_hash(plan))
    _rebuild_assert_inputs(plan, cancel)
    for unit in plan.units:
        _rebuild_assert_identity(unit.silver, cancel)
    return plan


def _rebuild_assert_inputs(plan: AdjFactorSilverRebuildPlan, cancel: Callable[[], None]) -> None:
    if _rebuild_plan_hash(plan) != plan.plan_hash:
        raise AdjFactorSilverRebuildError("rebuild_plan_invalid")
    if plan.budget != AdjFactorSilverRebuildBudget():
        raise AdjFactorSilverRebuildError("rebuild_budget_changed")
    for identity in (plan.lifecycle, *plan.source_code, *plan.raw_inputs):
        _rebuild_assert_identity(identity, cancel)
    root = Path(plan.lake_root)
    seen = set()
    for unit in plan.units:
        day = unit.partition_key
        if date.fromisoformat(day).isoformat() != day or day in seen:
            raise AdjFactorSilverRebuildError("rebuild_unit_invalid")
        seen.add(day)
        if (unit.raw.path != str(raw_adj_factor_path(root, day))
                or unit.silver.path != str(silver_adj_factor_path(root, day))
                or unit.original_rows - unit.expected_rows != unit.removed_rows
                or unit.removed_rows < 0):
            raise AdjFactorSilverRebuildError("rebuild_unit_scope_invalid")


def _rebuild_run_root(plan: AdjFactorSilverRebuildPlan, run_root: Path) -> None:
    _rebuild_check_path(run_root)
    if run_root.is_relative_to(Path(plan.lake_root)):
        raise AdjFactorSilverRebuildError("rebuild_staging_inside_lake")
    if plan.lake_root == DEFAULT_LAKE_ROOT and not run_root.is_relative_to(
        Path(DEFAULT_LAKE_STAGING_ROOT)
    ):
        raise AdjFactorSilverRebuildError("rebuild_staging_root_invalid")


def _rebuild_write_json(path: Path, payload: dict) -> None:
    _rebuild_check_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    _rebuild_check_path(temporary)
    with temporary.open("w") as handle:
        json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    _rebuild_fsync_directory(path.parent)


def _rebuild_fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def freeze_silver_adj_factor_rebuild(plan: AdjFactorSilverRebuildPlan, run_root: Path) -> None:
    """Persist only this operation's plan under staging, never under reports or Lake."""
    _rebuild_run_root(plan, run_root)
    _rebuild_assert_inputs(plan, lambda: None)
    target = run_root / "plan.json"
    if target.exists():
        if json.loads(target.read_text()) != json.loads(json.dumps(asdict(plan))):
            raise AdjFactorSilverRebuildError("rebuild_frozen_plan_conflict")
        return
    _rebuild_write_json(target, asdict(plan))


def load_silver_adj_factor_rebuild(run_root: Path) -> AdjFactorSilverRebuildPlan:
    _rebuild_check_path(run_root / "plan.json")
    if (run_root / "plan.json").stat().st_size > 16 * 1024**2:
        raise AdjFactorSilverRebuildError("rebuild_plan_size_exceeded")
    payload = json.loads((run_root / "plan.json").read_text())
    payload["lifecycle"] = AdjFactorFileFingerprint(**payload["lifecycle"])
    payload["budget"] = AdjFactorSilverRebuildBudget(**payload["budget"])
    for field in ("raw_inputs", "source_code"):
        payload[field] = tuple(AdjFactorFileFingerprint(**item) for item in payload[field])
    payload["units"] = tuple(AdjFactorSilverRebuildUnit(
        **{**unit, "raw": AdjFactorFileFingerprint(**unit["raw"]),
           "silver": AdjFactorFileFingerprint(**unit["silver"])}
    ) for unit in payload["units"])
    plan = AdjFactorSilverRebuildPlan(**payload)
    _rebuild_run_root(plan, run_root)
    _rebuild_assert_inputs(plan, lambda: None)
    return plan


def _rebuild_candidate_path(plan: AdjFactorSilverRebuildPlan, run_root: Path,
                            unit: AdjFactorSilverRebuildUnit) -> Path:
    return run_root / "candidates" / Path(unit.silver.path).relative_to(plan.lake_root)


def _rebuild_validate_candidate(connection, path: Path, unit: AdjFactorSilverRebuildUnit,
                                 plan: AdjFactorSilverRebuildPlan) -> None:
    from orchestrator.defs.checks.adj_factor_checks import (
        audit_adj_factor_candidate_rules,
    )

    rules = audit_adj_factor_candidate_rules(connection, path, unit.partition_key,
        raw=False, lifecycle_path=Path(plan.lifecycle.path))
    if rules["rows"] != unit.expected_rows or any(value for key, value in rules.items() if key != "rows"):
        raise AdjFactorSilverRebuildError("rebuild_candidate_rules_failed")
    expected = silver_adj_factor_select(Path(unit.raw.path), Path(plan.lifecycle.path))
    if connection.execute(f"""WITH expected AS ({expected}), actual AS (SELECT * FROM {read_parquet(path)})
        SELECT (SELECT count(*) FROM (SELECT * FROM expected EXCEPT ALL SELECT * FROM actual))
             + (SELECT count(*) FROM (SELECT * FROM actual EXCEPT ALL SELECT * FROM expected))""").fetchone()[0]:
        raise AdjFactorSilverRebuildError("rebuild_candidate_values_differ")


def build_silver_adj_factor_rebuild_candidates(
    plan: AdjFactorSilverRebuildPlan, run_root: Path, *,
    cancel: Callable[[], None] = lambda: None,
    progress: Callable[[int, int], None] = lambda completed, total: None,
) -> None:
    """Generate all changed day files under staging, with no formal writes."""
    _rebuild_run_root(plan, run_root)
    _rebuild_assert_inputs(plan, cancel)
    freeze_silver_adj_factor_rebuild(plan, run_root)
    if shutil.disk_usage(run_root).free < REBUILD_MIN_FREE_BYTES:
        raise AdjFactorSilverRebuildError("rebuild_staging_space_insufficient")
    completed, candidate_bytes = 0, 0
    candidate_records = {}
    changed = [unit for unit in plan.units if unit.removed_rows]
    for unit in plan.units:
        _rebuild_check_budget(cancel)
        _rebuild_assert_identity(unit.silver, cancel)
        if not unit.removed_rows:
            continue
        candidate = _rebuild_candidate_path(plan, run_root, unit)
        record_path = run_root / "checkpoints/candidates" / f"{unit.partition_key}.json"
        _rebuild_check_path(candidate)
        _rebuild_check_path(record_path)
        candidate.parent.mkdir(parents=True, exist_ok=True)
        with connect_configured_duckdb(_rebuild_settings(run_root / "temp")) as connection:
            if record_path.exists():
                record = json.loads(record_path.read_text())
                if record.get("plan_hash") != plan.plan_hash or not candidate.exists():
                    raise AdjFactorSilverRebuildError("rebuild_candidate_record_invalid")
                if _rebuild_fingerprint(candidate, cancel).sha256 != record["candidate_sha256"]:
                    raise AdjFactorSilverRebuildError("rebuild_candidate_drift")
            else:
                if candidate.exists():
                    candidate.unlink()  # Only an unfinished staging output; never a Lake file.
                connection.execute(copy_query_to_parquet(
                    silver_adj_factor_select(Path(unit.raw.path), Path(plan.lifecycle.path)), candidate,
                ))
            _rebuild_validate_candidate(connection, candidate, unit, plan)
        _rebuild_check_budget(cancel)
        identity = _rebuild_fingerprint(candidate, cancel)
        with candidate.open("rb") as handle:
            os.fsync(handle.fileno())
        _rebuild_fsync_directory(candidate.parent)
        candidate_bytes += identity.size
        if candidate_bytes > REBUILD_MAX_CANDIDATE_BYTES:
            raise AdjFactorSilverRebuildError("rebuild_candidate_budget_exceeded")
        _rebuild_assert_identity(unit.raw, cancel)
        _rebuild_assert_identity(unit.silver, cancel)
        _rebuild_write_json(record_path, {
            "plan_hash": plan.plan_hash, "partition_key": unit.partition_key,
            "candidate_sha256": identity.sha256, "candidate_bytes": identity.size,
        })
        candidate_records[unit.partition_key] = _rebuild_fingerprint(record_path, cancel).sha256
        completed += 1
        progress(completed, len(changed))
    _rebuild_assert_inputs(plan, cancel)
    _rebuild_write_json(run_root / "audit.json", {
        "plan_hash": plan.plan_hash, "status": "candidates_ready",
        "changed_files": len(changed), "removed_rows": sum(unit.removed_rows for unit in changed),
        "candidate_bytes": candidate_bytes,
        "candidate_records": candidate_records,
    })


def _rebuild_candidate_record(plan, run_root, unit, audit, cancel):
    path = run_root / "checkpoints/candidates" / f"{unit.partition_key}.json"
    frozen = audit.get("candidate_records", {}).get(unit.partition_key)
    if not frozen or _rebuild_fingerprint(path, cancel).sha256 != frozen:
        raise AdjFactorSilverRebuildError("rebuild_candidate_record_drift")
    record = json.loads(path.read_text())
    if record.get("plan_hash") != plan.plan_hash or record.get("partition_key") != unit.partition_key:
        raise AdjFactorSilverRebuildError("rebuild_candidate_record_invalid")
    return record


def promote_silver_adj_factor_rebuild(
    plan: AdjFactorSilverRebuildPlan, run_root: Path, *, maintenance_confirmed: bool = False,
    cancel: Callable[[], None] = lambda: None,
    progress: Callable[[int, int], None] = lambda completed, total: None,
) -> None:
    """Explicit per-file atomic promote; interruption preserves completed days."""
    if not maintenance_confirmed:
        raise AdjFactorSilverRebuildError("rebuild_maintenance_required")
    _rebuild_run_root(plan, run_root)
    _rebuild_assert_inputs(plan, cancel)
    _rebuild_check_path(run_root / "audit.json")
    if not (run_root / "audit.json").is_file():
        raise AdjFactorSilverRebuildError("rebuild_full_candidates_not_ready")
    audit = json.loads((run_root / "audit.json").read_text())
    if audit.get("plan_hash") != plan.plan_hash or audit.get("status") not in ("candidates_ready", "files_verified"):
        raise AdjFactorSilverRebuildError("rebuild_full_candidates_not_ready")
    changed = [unit for unit in plan.units if unit.removed_rows]
    # Validate every remaining candidate before the first formal replace.
    for unit in plan.units:
        target = Path(unit.silver.path)
        current = _rebuild_fingerprint(target, cancel)
        if not unit.removed_rows:
            if current != unit.silver:
                raise AdjFactorSilverRebuildError("rebuild_unchanged_target_drift")
            continue
        record = _rebuild_candidate_record(plan, run_root, unit, audit, cancel)
        if current.sha256 == record["candidate_sha256"]:
            continue
        if current != unit.silver:
            raise AdjFactorSilverRebuildError("rebuild_target_drift")
        candidate = _rebuild_candidate_path(plan, run_root, unit)
        if _rebuild_fingerprint(candidate, cancel).sha256 != record["candidate_sha256"]:
            raise AdjFactorSilverRebuildError("rebuild_candidate_drift")
        with connect_configured_duckdb(_rebuild_settings(run_root / "temp")) as connection:
            _rebuild_validate_candidate(connection, candidate, unit, plan)
    for completed, unit in enumerate(changed, 1):
        _rebuild_check_budget(cancel)
        _rebuild_assert_identity(plan.lifecycle, cancel)
        for identity in plan.source_code:
            _rebuild_assert_identity(identity, cancel)
        _rebuild_assert_identity(unit.raw, cancel)
        target = Path(unit.silver.path)
        record = _rebuild_candidate_record(plan, run_root, unit, audit, cancel)
        current = _rebuild_fingerprint(target, cancel)
        if current.sha256 != record["candidate_sha256"]:
            if current != unit.silver:
                raise AdjFactorSilverRebuildError("rebuild_target_drift")
            candidate = _rebuild_candidate_path(plan, run_root, unit)
            if _rebuild_fingerprint(candidate, cancel).sha256 != record["candidate_sha256"]:
                raise AdjFactorSilverRebuildError("rebuild_candidate_drift")
            if candidate.stat().st_dev != target.parent.stat().st_dev:
                raise AdjFactorSilverRebuildError("rebuild_cross_filesystem")
            cancel()
            os.replace(candidate, target)
            _rebuild_fsync_directory(target.parent)
            if _rebuild_fingerprint(target, cancel).sha256 != record["candidate_sha256"]:
                raise AdjFactorSilverRebuildError("rebuild_promoted_file_invalid")
        _rebuild_write_json(run_root / "checkpoints/promoted" / f"{unit.partition_key}.json", {
            "plan_hash": plan.plan_hash, "partition_key": unit.partition_key,
            "target_sha256": record["candidate_sha256"],
        })
        progress(completed, len(changed))
    verify_silver_adj_factor_rebuild(plan, run_root, cancel=cancel)


def verify_silver_adj_factor_rebuild(plan: AdjFactorSilverRebuildPlan, run_root: Path, *,
                                    cancel: Callable[[], None] = lambda: None) -> dict:
    """One final physical reconciliation of this frozen operation."""
    _rebuild_run_root(plan, run_root)
    _rebuild_assert_inputs(plan, cancel)
    _rebuild_check_path(run_root / "audit.json")
    audit = json.loads((run_root / "audit.json").read_text())
    if audit.get("plan_hash") != plan.plan_hash:
        raise AdjFactorSilverRebuildError("rebuild_full_candidates_not_ready")
    units = plan.units
    for offset in range(0, len(units), REBUILD_BATCH_DATES):
        selected = units[offset:offset + REBUILD_BATCH_DATES]
        for unit in selected:
            target = Path(unit.silver.path)
            if unit.removed_rows:
                record = _rebuild_candidate_record(plan, run_root, unit, audit, cancel)
                if _rebuild_fingerprint(target, cancel).sha256 != record["candidate_sha256"]:
                    raise AdjFactorSilverRebuildError("rebuild_formal_file_drift")
            else:
                _rebuild_assert_identity(unit.silver, cancel)
        with connect_configured_duckdb(_rebuild_settings(run_root / "temp")) as connection:
            observed = _rebuild_batch_comparison(connection,
                [Path(unit.raw.path) for unit in selected], [Path(unit.silver.path) for unit in selected],
                Path(plan.lifecycle.path))
        if any(observed.get(unit.partition_key) != (unit.expected_rows, unit.expected_rows, 0) for unit in selected):
            raise AdjFactorSilverRebuildError("rebuild_formal_values_differ")
    _rebuild_assert_inputs(plan, cancel)
    result = {"plan_hash": plan.plan_hash, "status": "files_verified",
              "changed_files": sum(bool(unit.removed_rows) for unit in units),
              "removed_rows": sum(unit.removed_rows for unit in units),
              "rows": sum(unit.expected_rows for unit in units),
              "candidate_records": audit["candidate_records"]}
    _rebuild_write_json(run_root / "audit.json", result)
    return result


def silver_adj_factor_rebuild_check_job(definitions: dg.Definitions) -> dg.JobDefinition:
    """Use only the four existing checks; never execute the factor asset again."""
    from orchestrator.defs.sensors.readiness import SILVER_ADJ_FACTOR_BLOCKING_CHECKS

    return definitions.resolve_job_def("silver_adj_factor_update_job").get_subset(
        asset_selection=set(), asset_check_selection={
            dg.AssetCheckKey(dg.AssetKey("silver_adj_factor"), name)
            for name in SILVER_ADJ_FACTOR_BLOCKING_CHECKS
        },
    )


def preview_silver_adj_factor_rebuild_events(plan: AdjFactorSilverRebuildPlan) -> dict:
    count = sum(bool(unit.removed_rows) for unit in plan.units)
    return {"asset_key": "silver_adj_factor", "materializations": count,
            "checks": 4 * count, "real_check_runs": count, "asset_executions": 0}


def report_silver_adj_factor_rebuild_events(
    plan: AdjFactorSilverRebuildPlan, run_root: Path, *, instance: dg.DagsterInstance,
    definitions: dg.Definitions, maintenance_confirmed: bool = False,
    cancel: Callable[[], None] = lambda: None,
    progress: Callable[[int, int], None] = lambda completed, total: None,
) -> dict:
    """Register actual replaced files, then run real checks against each new materialization."""
    from orchestrator.defs.sensors.readiness import SILVER_ADJ_FACTOR_BLOCKING_CHECKS

    if not maintenance_confirmed:
        raise AdjFactorSilverRebuildError("rebuild_event_maintenance_required")
    verify_silver_adj_factor_rebuild(plan, run_root, cancel=cancel)
    job = silver_adj_factor_rebuild_check_job(definitions)
    changed = [unit for unit in plan.units if unit.removed_rows]
    for completed, unit in enumerate(changed, 1):
        _rebuild_check_budget(cancel)
        _rebuild_assert_identity(plan.lifecycle, cancel)
        day = unit.partition_key
        event_path = run_root / "checkpoints/events" / f"{day}.json"
        _rebuild_check_path(event_path)
        target_hash = _rebuild_fingerprint(Path(unit.silver.path), cancel).sha256
        candidate_record = json.loads((run_root / "checkpoints/candidates" / f"{day}.json").read_text())
        if target_hash != candidate_record["candidate_sha256"]:
            raise AdjFactorSilverRebuildError("rebuild_event_target_drift")
        records_filter = dg.AssetRecordsFilter(
            asset_key=dg.AssetKey("silver_adj_factor"), asset_partitions=[day],
        )
        latest = instance.fetch_materializations(records_filter, limit=1).records
        if not latest or latest[0].asset_materialization.metadata.get("factor_silver_rebuild_plan_hash", dg.MetadataValue.text("")).value != plan.plan_hash:
            instance.report_runless_asset_event(dg.AssetMaterialization(
                asset_key="silver_adj_factor", partition=day, metadata={
                    "dagster/row_count": unit.expected_rows,
                    "factor_silver_rebuild_plan_hash": plan.plan_hash,
                    "target_sha256": target_hash, "removed_rows": unit.removed_rows,
                    "goldenshare/summary": "按当前上市股票名单重建复权因子Silver；Raw和行情未改写。",
                },
            ))
            latest = instance.fetch_materializations(records_filter, limit=1).records
        materialization_id = latest[0].storage_id
        if (latest[0].asset_materialization.metadata["target_sha256"].value != target_hash
                or latest[0].asset_materialization.metadata["factor_silver_rebuild_plan_hash"].value != plan.plan_hash):
            raise AdjFactorSilverRebuildError("rebuild_event_materialization_drift")
        if event_path.exists():
            recorded = json.loads(event_path.read_text())
            if recorded.get("plan_hash") != plan.plan_hash:
                raise AdjFactorSilverRebuildError("rebuild_event_record_invalid")
            run = instance.get_run_by_id(recorded["run_id"])
            if (run and run.is_success and recorded.get("checks_verified") is True
                    and recorded.get("materialization_id") == materialization_id):
                progress(completed, len(changed))
                continue
        cancel()
        result = job.execute_in_process(instance=instance, partition_key=day, raise_on_error=False)
        event_record = {"plan_hash": plan.plan_hash, "materialization_id": materialization_id,
                        "run_id": result.run_id, "checks_verified": False}
        _rebuild_write_json(event_path, event_record)
        evaluations = result.get_asset_check_evaluations()
        if (not result.success or len(evaluations) != 4
                or {evaluation.check_name for evaluation in evaluations} != set(SILVER_ADJ_FACTOR_BLOCKING_CHECKS)
                or any(not evaluation.passed or evaluation.target_materialization_data is None
                       or evaluation.target_materialization_data.storage_id != materialization_id
                       for evaluation in evaluations)):
            raise AdjFactorSilverRebuildError("rebuild_real_checks_failed")
        _rebuild_write_json(event_path, {**event_record, "checks_verified": True})
        progress(completed, len(changed))
    return preview_silver_adj_factor_rebuild_events(plan)
