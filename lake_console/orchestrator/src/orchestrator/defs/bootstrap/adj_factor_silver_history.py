import hashlib
import json
import os
import re
import resource
import stat
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

import dagster as dg

from orchestrator.defs.assets.adj_factor import (
    SilverAdjFactorPartitionWriteResult,
)
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
)
from orchestrator.defs.duckdb_sql import (
    adj_factor_retained_stock_select,
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
from orchestrator.defs.run_contracts.adj_factor import (
    ADJ_FACTOR_RETIRED_RETENTION_START_DATE,
)
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
    if partition_key < ADJ_FACTOR_RETIRED_RETENTION_START_DATE:
        raise ValueError("historical_partition_requires_explicit_restore")
    if not TRADE_DATE_PARTITION_PATTERN.match(partition_key):
        raise ValueError(f"Invalid trade_date partition key: {partition_key}")

    raise ValueError("factor_history_write_requires_silver_adj_factor_update_job")


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
    # Materialize one bounded batch once; repeated view expansion retains large query plans.
    source = " UNION ALL ".join(f"SELECT * FROM {read_parquet(path)}" for path in silver_paths)
    connection.execute(f"CREATE OR REPLACE TEMP TABLE factor_rebuild_before AS {source}")
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE factor_rebuild_expected AS "
        + silver_adj_factor_select(raw_paths, lifecycle_path)
    )
    retained_sql = adj_factor_retained_stock_select(lifecycle_path)
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
    """The old removal-only migration is retired; use the normal Silver job."""
    raise AdjFactorSilverRebuildError("legacy_current_listed_rebuild_retired")


def _rebuild_assert_inputs(plan: AdjFactorSilverRebuildPlan, cancel: Callable[[], None]) -> None:
    raise AdjFactorSilverRebuildError("legacy_current_listed_rebuild_retired")


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
    """Removal-only migration is retired under the retained-factor contract."""
    raise AdjFactorSilverRebuildError("legacy_current_listed_rebuild_retired")


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
    if _rebuild_plan_hash(plan) != plan.plan_hash:
        raise AdjFactorSilverRebuildError("rebuild_plan_invalid")
    return plan


def _rebuild_candidate_path(plan: AdjFactorSilverRebuildPlan, run_root: Path,
                            unit: AdjFactorSilverRebuildUnit) -> Path:
    return run_root / "candidates" / Path(unit.silver.path).relative_to(plan.lake_root)


def _rebuild_validate_candidate(connection, path: Path, unit: AdjFactorSilverRebuildUnit,
                                 plan: AdjFactorSilverRebuildPlan) -> None:
    from orchestrator.defs.stock_factor_price_checks import (
        audit_adj_factor_candidate_rules,
    )

    rules = audit_adj_factor_candidate_rules(connection, path, unit.partition_key,
        raw=False, lifecycle_path=Path(plan.lifecycle.path), raw_path=Path(unit.raw.path))
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
    """Removal-only migration is retired under the retained-factor contract."""
    raise AdjFactorSilverRebuildError("legacy_current_listed_rebuild_retired")


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
    """Removal-only migration is retired under the retained-factor contract."""
    raise AdjFactorSilverRebuildError("legacy_current_listed_rebuild_retired")


def verify_silver_adj_factor_rebuild(plan: AdjFactorSilverRebuildPlan, run_root: Path, *,
                                    cancel: Callable[[], None] = lambda: None) -> dict:
    """Removal-only migration is retired under the retained-factor contract."""
    raise AdjFactorSilverRebuildError("legacy_current_listed_rebuild_retired")


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
    """Removal-only migration is retired under the retained-factor contract."""
    raise AdjFactorSilverRebuildError("legacy_current_listed_rebuild_retired")
