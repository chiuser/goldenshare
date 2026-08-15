"""Plan-gated, resumable publication of major-index daily nine-turn history."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

import duckdb

from orchestrator.defs.assets.index_daily_nineturn_prod_core import (
    load_gold_major_index_daily_nineturn_rows_with_connection,
)
from orchestrator.defs.major_index_nineturn_integrity import (
    audit_major_index_nineturn_integrity,
)
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    DEFAULT_LAKE_STAGING_ROOT,
    gold_major_index_daily_nineturn_path,
    gold_market_major_indices_daily_path,
)
from orchestrator.defs.prod_db.index_daily_nineturn import (
    audit_prod_core_index_daily_nineturn_checkpoint_partitions,
    audit_prod_core_index_daily_nineturn_partition,
    replace_prod_core_index_daily_nineturn_partition,
)
from orchestrator.defs.resources import DuckDBResource, ProdPostgresWriteResource

SCHEMA_VERSION = 1
PLAN_PHASE = "major_index_daily_nineturn_serving_history_plan"
CHECKPOINT_PHASE = "major_index_daily_nineturn_serving_history_checkpoint"
MAX_BATCH_PARTITION_COUNT = 20
MAX_SAMPLE_PARTITION_COUNT = 3
MAX_BATCH_COUNT_PER_PROCESS = 10
HISTORY_DUCKDB_MEMORY_LIMIT = "128MB"
HISTORY_DUCKDB_THREADS = 1
_BatchItem = TypeVar("_BatchItem")


class MajorIndexDailyNineturnServingHistoryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MajorIndexDailyNineturnServingPartition:
    partition_key: str
    nineturn_relative_path: str
    nineturn_size: int
    nineturn_mtime_ns: int
    daily_relative_path: str
    daily_size: int
    daily_mtime_ns: int
    row_count: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MajorIndexDailyNineturnServingPlan:
    report_path: Path
    lake_root: Path
    staging_root: Path
    plan_fingerprint: str
    batch_partition_limit: int
    partitions: tuple[MajorIndexDailyNineturnServingPartition, ...]
    stop_reasons: tuple[str, ...]
    report: Mapping[str, object]

    @property
    def should_stop(self) -> bool:
        return bool(self.stop_reasons)

    def to_summary_dict(self) -> dict[str, object]:
        return {
            "report_path": str(self.report_path),
            "plan_fingerprint": self.plan_fingerprint,
            "partition_count": len(self.partitions),
            "source_row_count": sum(item.row_count for item in self.partitions),
            "first_partition_key": (
                self.partitions[0].partition_key if self.partitions else None
            ),
            "last_partition_key": (
                self.partitions[-1].partition_key if self.partitions else None
            ),
            "batch_partition_limit": self.batch_partition_limit,
            "estimated_batch_count": (
                (len(self.partitions) + self.batch_partition_limit - 1)
                // self.batch_partition_limit
            ),
            "should_stop": self.should_stop,
            "stop_reasons": list(self.stop_reasons),
        }


def plan_major_index_daily_nineturn_serving_history(
    *,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    staging_root: Path = Path(DEFAULT_LAKE_STAGING_ROOT),
    duckdb_resource: DuckDBResource,
    start_date: str | None = None,
    end_date: str | None = None,
    batch_partition_limit: int = MAX_BATCH_PARTITION_COUNT,
    output_dir: Path,
) -> MajorIndexDailyNineturnServingPlan:
    """Freeze exact daily Gold inputs without writing Prod or Lake."""

    _validate_batch_partition_limit(batch_partition_limit)
    root, staging = _validate_roots(lake_root=lake_root, staging_root=staging_root)
    selected = _selected_partition_keys(root, start_date=start_date, end_date=end_date)
    stop_reasons: list[str] = []
    partitions: list[MajorIndexDailyNineturnServingPartition] = []
    if not selected:
        stop_reasons.append("empty_partition_scope")
    for batch in _partition_batches(selected, batch_partition_limit):
        with duckdb_resource.connect() as connection:
            _configure_history_duckdb(connection)
            for partition_key in batch:
                nineturn_path = gold_major_index_daily_nineturn_path(
                    root, partition_key
                )
                daily_path = gold_market_major_indices_daily_path(root, partition_key)
                if not nineturn_path.is_file() or not daily_path.is_file():
                    stop_reasons.append(f"{partition_key}:source_missing")
                    continue
                diagnostics = audit_major_index_nineturn_integrity(
                    connection,
                    target_path=nineturn_path,
                    source_paths=(daily_path,),
                    partition_key=partition_key,
                    freq=None,
                )
                if not diagnostics.passed:
                    stop_reasons.append(f"{partition_key}:source_contract_failed")
                    continue
                nineturn_stat = nineturn_path.stat()
                daily_stat = daily_path.stat()
                partitions.append(
                    MajorIndexDailyNineturnServingPartition(
                        partition_key=partition_key,
                        nineturn_relative_path=_relative(nineturn_path, root),
                        nineturn_size=nineturn_stat.st_size,
                        nineturn_mtime_ns=nineturn_stat.st_mtime_ns,
                        daily_relative_path=_relative(daily_path, root),
                        daily_size=daily_stat.st_size,
                        daily_mtime_ns=daily_stat.st_mtime_ns,
                        row_count=diagnostics.checked_row_count,
                    )
                )
    normalized = tuple(sorted(partitions, key=lambda item: item.partition_key))
    stop_reasons_tuple = tuple(sorted(set(stop_reasons)))
    fingerprint_payload = _fingerprint_payload(
        lake_root=root,
        staging_root=staging,
        batch_partition_limit=batch_partition_limit,
        partitions=normalized,
        stop_reasons=stop_reasons_tuple,
    )
    fingerprint = _hash_payload(fingerprint_payload)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / (
        "major_index_daily_nineturn_serving_plan_"
        f"{datetime.now(UTC).strftime('%Y%m%d_%H%M%S_%f')}.json"
    )
    report = {
        **fingerprint_payload,
        "phase": PLAN_PHASE,
        "read_only": True,
        "plan_fingerprint": fingerprint,
        "partition_count": len(normalized),
        "source_row_count": sum(item.row_count for item in normalized),
        "estimated_batch_count": (
            (len(normalized) + batch_partition_limit - 1) // batch_partition_limit
        ),
        "should_stop": bool(stop_reasons_tuple),
    }
    _write_json_atomic(report_path, report)
    return MajorIndexDailyNineturnServingPlan(
        report_path=report_path,
        lake_root=root,
        staging_root=staging,
        plan_fingerprint=fingerprint,
        batch_partition_limit=batch_partition_limit,
        partitions=normalized,
        stop_reasons=stop_reasons_tuple,
        report=report,
    )


def load_major_index_daily_nineturn_serving_plan(
    report_path: Path,
) -> MajorIndexDailyNineturnServingPlan:
    try:
        payload = json.loads(Path(report_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MajorIndexDailyNineturnServingHistoryError(
            "Serving plan report is unreadable."
        ) from error
    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("phase") != PLAN_PHASE
        or payload.get("read_only") is not True
    ):
        raise MajorIndexDailyNineturnServingHistoryError(
            "Serving plan report contract is invalid."
        )
    plan = MajorIndexDailyNineturnServingPlan(
        report_path=Path(report_path).resolve(),
        lake_root=Path(str(payload["lake_root"])).resolve(),
        staging_root=Path(str(payload["staging_root"])).resolve(),
        plan_fingerprint=str(payload["plan_fingerprint"]),
        batch_partition_limit=int(payload["batch_partition_limit"]),
        partitions=tuple(
            MajorIndexDailyNineturnServingPartition(**dict(item))
            for item in payload["partitions"]
        ),
        stop_reasons=tuple(str(value) for value in payload["stop_reasons"]),
        report=payload,
    )
    if _plan_fingerprint(plan) != plan.plan_fingerprint:
        raise MajorIndexDailyNineturnServingHistoryError(
            "Serving plan fingerprint drifted."
        )
    return plan


def publish_major_index_daily_nineturn_serving_history(
    *,
    plan: MajorIndexDailyNineturnServingPlan,
    expected_plan_fingerprint: str,
    duckdb_resource: DuckDBResource,
    prod_postgres_write: ProdPostgresWriteResource,
    checkpoint_path: Path,
    mode: str = "batch",
    sample_partition_keys: Sequence[str] = (),
    batch_count_limit: int = 1,
    progress_callback: Callable[[Mapping[str, object]], None] | None = None,
) -> Mapping[str, object]:
    """Publish one explicit sample or at most ten reviewed 20-day batches."""

    if plan.should_stop or plan.plan_fingerprint != expected_plan_fingerprint:
        raise MajorIndexDailyNineturnServingHistoryError(
            "Serving plan stopped or fingerprint mismatched."
        )
    _validate_batch_count_limit(batch_count_limit)
    _validate_source_identities(plan)
    checkpoint = _validated_checkpoint_path(
        checkpoint_path=checkpoint_path, staging_root=plan.staging_root
    )
    completed = _load_checkpoint(
        checkpoint, plan_fingerprint=plan.plan_fingerprint
    )
    resumed = _validate_completed_partitions(
        plan=plan,
        completed=completed,
        prod_postgres_write=prod_postgres_write,
    )
    selected = _publication_selection(
        plan=plan,
        completed=completed,
        mode=mode,
        sample_partition_keys=sample_partition_keys,
        batch_count_limit=batch_count_limit,
    )
    started = time.perf_counter()
    published: list[str] = []
    for batch in _partition_batches(selected, plan.batch_partition_limit):
        with (
            duckdb_resource.connect() as duckdb_connection,
            prod_postgres_write.connect() as write_connection,
            prod_postgres_write.connect_readonly() as read_connection,
        ):
            _configure_history_duckdb(duckdb_connection)
            for partition_key in batch:
                rows = load_gold_major_index_daily_nineturn_rows_with_connection(
                    connection=duckdb_connection,
                    source_path=gold_major_index_daily_nineturn_path(
                        plan.lake_root, partition_key
                    ),
                    daily_source_path=gold_market_major_indices_daily_path(
                        plan.lake_root, partition_key
                    ),
                    partition_key=partition_key,
                )
                replace_prod_core_index_daily_nineturn_partition(
                    connection=write_connection,
                    rows=rows,
                    partition_key=partition_key,
                )
                write_connection.commit()
                try:
                    audit = audit_prod_core_index_daily_nineturn_partition(
                        connection=read_connection,
                        rows=rows,
                        partition_key=partition_key,
                    )
                finally:
                    read_connection.rollback()
                if not audit.passed:
                    raise MajorIndexDailyNineturnServingHistoryError(
                        f"Serving read-back failed: {partition_key}."
                    )
                completed[partition_key] = audit.expected_content_hash
                _write_checkpoint(
                    checkpoint,
                    plan_fingerprint=plan.plan_fingerprint,
                    completed=completed,
                )
                published.append(partition_key)
            if progress_callback is not None and batch:
                progress_callback(
                    {
                        "event": "batch_published",
                        "batch_first_partition_key": batch[0],
                        "batch_last_partition_key": batch[-1],
                        "batch_published_partition_count": len(batch),
                        "completed_partition_count": len(completed),
                        "total_partition_count": len(plan.partitions),
                        "remaining_partition_count": len(plan.partitions)
                        - len(completed),
                    }
                )
    return {
        "plan_fingerprint": plan.plan_fingerprint,
        "mode": mode,
        "selected_partition_count": len(selected),
        "published_partition_count": len(published),
        "resumed_partition_count": len(resumed),
        "completed_partition_count": len(completed),
        "remaining_partition_count": len(plan.partitions) - len(completed),
        "processed_batch_count": (
            (len(selected) + plan.batch_partition_limit - 1)
            // plan.batch_partition_limit
        ),
        "checkpoint_path": str(checkpoint),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
    }


def _selected_partition_keys(
    lake_root: Path, *, start_date: str | None, end_date: str | None
) -> tuple[str, ...]:
    discovered = tuple(
        sorted(
            path.parent.name.removeprefix("trade_date=")
            for path in (
                lake_root / "gold/indicator/major_index_daily_nineturn"
            ).glob("trade_date=*/part-000.parquet")
            if path.is_file()
        )
    )
    return tuple(
        value
        for value in discovered
        if (start_date is None or value >= start_date)
        and (end_date is None or value <= end_date)
    )


def _publication_selection(*, plan, completed, mode, sample_partition_keys, batch_count_limit):
    all_keys = tuple(item.partition_key for item in plan.partitions)
    pending = tuple(value for value in all_keys if value not in completed)
    if mode == "batch":
        if sample_partition_keys:
            raise MajorIndexDailyNineturnServingHistoryError(
                "Batch mode does not accept sample partitions."
            )
        return pending[: plan.batch_partition_limit * batch_count_limit]
    if mode != "sample":
        raise MajorIndexDailyNineturnServingHistoryError("Unsupported serving mode.")
    samples = tuple(dict.fromkeys(str(value) for value in sample_partition_keys))
    if not samples or len(samples) > MAX_SAMPLE_PARTITION_COUNT:
        raise MajorIndexDailyNineturnServingHistoryError(
            "Sample mode requires one to three explicit partitions."
        )
    if set(samples) - set(all_keys):
        raise MajorIndexDailyNineturnServingHistoryError(
            "Sample partition is outside the reviewed plan."
        )
    return tuple(value for value in samples if value not in completed)


def _validate_completed_partitions(*, plan, completed, prod_postgres_write):
    unknown = tuple(sorted(set(completed) - {item.partition_key for item in plan.partitions}))
    if unknown:
        raise MajorIndexDailyNineturnServingHistoryError(
            f"Checkpoint contains unknown dates: {unknown[:20]}."
        )
    if not completed:
        return ()
    with prod_postgres_write.connect_readonly() as connection:
        try:
            audit = audit_prod_core_index_daily_nineturn_checkpoint_partitions(
                connection=connection, expected_content_hashes=completed
            )
        finally:
            connection.rollback()
    if not audit.passed:
        raise MajorIndexDailyNineturnServingHistoryError(
            "Checkpoint/serving drift: " f"{audit.failed_partition_keys[:20]}."
        )
    return tuple(sorted(completed))


def _validate_source_identities(plan: MajorIndexDailyNineturnServingPlan) -> None:
    failures: list[str] = []
    for partition in plan.partitions:
        for label, relative, size, mtime_ns in (
            (
                "nineturn",
                partition.nineturn_relative_path,
                partition.nineturn_size,
                partition.nineturn_mtime_ns,
            ),
            (
                "daily",
                partition.daily_relative_path,
                partition.daily_size,
                partition.daily_mtime_ns,
            ),
        ):
            path = _validated_source_path(plan.lake_root, relative)
            stat = path.stat()
            if stat.st_size != size or stat.st_mtime_ns != mtime_ns:
                failures.append(f"{partition.partition_key}:{label}:changed")
        if len(failures) >= 20:
            break
    if failures:
        raise MajorIndexDailyNineturnServingHistoryError(
            f"Serving source plan is stale: {tuple(failures)}."
        )


def _validated_source_path(lake_root: Path, relative_path: str) -> Path:
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise MajorIndexDailyNineturnServingHistoryError("Unsafe source path.")
    path = (lake_root / relative).resolve(strict=True)
    if not path.is_file() or not path.is_relative_to(lake_root.resolve()):
        raise MajorIndexDailyNineturnServingHistoryError("Invalid source path.")
    return path


def _partition_batches(items: Sequence[_BatchItem], limit: int):
    return tuple(tuple(items[index : index + limit]) for index in range(0, len(items), limit))


def _configure_history_duckdb(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(f"SET memory_limit = '{HISTORY_DUCKDB_MEMORY_LIMIT}'")
    connection.execute(f"SET threads = {HISTORY_DUCKDB_THREADS}")
    connection.execute("SET preserve_insertion_order = false")


def _load_checkpoint(path: Path, *, plan_fingerprint: str) -> dict[str, str]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("phase") != CHECKPOINT_PHASE
        or payload.get("plan_fingerprint") != plan_fingerprint
        or not isinstance(payload.get("completed"), dict)
    ):
        raise MajorIndexDailyNineturnServingHistoryError(
            "Serving checkpoint contract is invalid."
        )
    return {str(key): str(value) for key, value in payload["completed"].items()}


def _write_checkpoint(path: Path, *, plan_fingerprint: str, completed) -> None:
    _write_json_atomic(
        path,
        {
            "schema_version": SCHEMA_VERSION,
            "phase": CHECKPOINT_PHASE,
            "plan_fingerprint": plan_fingerprint,
            "completed": dict(sorted(completed.items())),
            "completed_partition_count": len(completed),
            "updated_at": datetime.now(UTC).isoformat(),
        },
    )


def _validated_checkpoint_path(*, checkpoint_path: Path, staging_root: Path) -> Path:
    path = Path(checkpoint_path).resolve()
    if not path.is_relative_to(staging_root.resolve()):
        raise MajorIndexDailyNineturnServingHistoryError(
            "Serving checkpoint must be below staging."
        )
    return path


def _validate_roots(*, lake_root: Path, staging_root: Path) -> tuple[Path, Path]:
    root = Path(lake_root).resolve()
    staging = Path(staging_root).resolve()
    if root == Path(DEFAULT_LAKE_ROOT).resolve() and staging != Path(
        DEFAULT_LAKE_STAGING_ROOT
    ).resolve():
        raise MajorIndexDailyNineturnServingHistoryError(
            "Formal serving publication must use fixed staging."
        )
    if root == staging:
        raise MajorIndexDailyNineturnServingHistoryError(
            "Lake and staging roots must differ."
        )
    return root, staging


def _validate_batch_partition_limit(value: int) -> None:
    if isinstance(value, bool) or not 1 <= value <= MAX_BATCH_PARTITION_COUNT:
        raise MajorIndexDailyNineturnServingHistoryError(
            "Batch partition limit must be within 1..20."
        )


def _validate_batch_count_limit(value: int) -> None:
    if isinstance(value, bool) or not 1 <= value <= MAX_BATCH_COUNT_PER_PROCESS:
        raise MajorIndexDailyNineturnServingHistoryError(
            "Batch count limit must be within 1..10."
        )


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise MajorIndexDailyNineturnServingHistoryError(
            "Serving source is outside the reviewed Lake root."
        ) from error


def _fingerprint_payload(*, lake_root, staging_root, batch_partition_limit, partitions, stop_reasons):
    return {
        "schema_version": SCHEMA_VERSION,
        "lake_root": str(lake_root.resolve()),
        "staging_root": str(staging_root.resolve()),
        "batch_partition_limit": batch_partition_limit,
        "partitions": [item.to_dict() for item in partitions],
        "stop_reasons": list(stop_reasons),
    }


def _plan_fingerprint(plan: MajorIndexDailyNineturnServingPlan) -> str:
    return _hash_payload(
        _fingerprint_payload(
            lake_root=plan.lake_root,
            staging_root=plan.staging_root,
            batch_partition_limit=plan.batch_partition_limit,
            partitions=plan.partitions,
            stop_reasons=plan.stop_reasons,
        )
    )


def _hash_payload(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


__all__ = [
    "MajorIndexDailyNineturnServingHistoryError",
    "MajorIndexDailyNineturnServingPlan",
    "load_major_index_daily_nineturn_serving_plan",
    "plan_major_index_daily_nineturn_serving_history",
    "publish_major_index_daily_nineturn_serving_history",
]
