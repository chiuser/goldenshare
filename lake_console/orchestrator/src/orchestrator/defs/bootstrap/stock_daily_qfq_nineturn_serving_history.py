"""Plan-gated, resumable history publisher for stock daily QFQ nine-turn."""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

import duckdb

from orchestrator.defs.assets.stock_daily_qfq_nineturn_prod_core import (
    audit_gold_stock_daily_qfq_nineturn_for_prod_sync,
    load_gold_stock_daily_qfq_nineturn_rows_with_connection,
)
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    DEFAULT_LAKE_STAGING_ROOT,
    gold_stock_daily_qfq_nineturn_path,
    gold_stock_daily_qfq_path,
)
from orchestrator.defs.prod_db.stock_daily_qfq_nineturn import (
    audit_prod_core_stock_daily_qfq_nineturn_checkpoint_partitions,
    audit_prod_core_stock_daily_qfq_nineturn_partition,
    replace_prod_core_stock_daily_qfq_nineturn_partition,
)
from orchestrator.defs.resources import (
    DuckDBResource,
    ProdPostgresWriteResource,
)

SCHEMA_VERSION = 2
PLAN_PHASE = "stock_daily_qfq_nineturn_serving_history_plan"
CHECKPOINT_PHASE = "stock_daily_qfq_nineturn_serving_history_checkpoint"
MAX_BATCH_PARTITION_COUNT = 20
MAX_SAMPLE_PARTITION_COUNT = 3
MAX_BATCH_COUNT_PER_RUN = 10
HISTORY_DUCKDB_MEMORY_LIMIT = "128MB"
HISTORY_DUCKDB_THREADS = 1
_BatchItemT = TypeVar("_BatchItemT")


class StockDailyQfqNineTurnServingHistoryError(RuntimeError):
    """Raised when a serving history publication gate fails."""


@dataclass(frozen=True, slots=True)
class ServingHistoryPartition:
    partition_key: str
    source_relative_path: str
    source_size: int
    source_mtime_ns: int
    row_count: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class StockDailyQfqNineTurnServingHistoryPlan:
    report_path: Path
    lake_root: Path
    staging_root: Path
    plan_fingerprint: str
    batch_partition_limit: int
    partitions: tuple[ServingHistoryPartition, ...]
    stop_reasons: tuple[str, ...]
    report: Mapping[str, object]

    @property
    def should_stop(self) -> bool:
        return bool(self.stop_reasons)

    def to_summary_dict(self) -> dict[str, object]:
        """Return a constant-size operator summary; the report file keeps details."""

        return {
            "phase": PLAN_PHASE,
            "read_only": True,
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


@dataclass(frozen=True, slots=True)
class StockDailyQfqNineTurnServingHistoryPublishReport:
    plan_fingerprint: str
    mode: str
    selected_partition_keys: tuple[str, ...]
    published_partition_keys: tuple[str, ...]
    resumed_partition_keys: tuple[str, ...]
    remaining_partition_count: int
    processed_batch_count: int
    checkpoint_path: Path
    elapsed_ms: float

    def to_dict(self) -> dict[str, object]:
        """Return a constant-size result summary without full partition arrays."""

        return {
            "plan_fingerprint": self.plan_fingerprint,
            "mode": self.mode,
            **_partition_key_summary("selected", self.selected_partition_keys),
            **_partition_key_summary("published", self.published_partition_keys),
            **_partition_key_summary("resumed", self.resumed_partition_keys),
            "remaining_partition_count": self.remaining_partition_count,
            "processed_batch_count": self.processed_batch_count,
            "checkpoint_path": str(self.checkpoint_path),
            "elapsed_ms": self.elapsed_ms,
        }


def plan_stock_daily_qfq_nineturn_serving_history(
    *,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    staging_root: Path = Path(DEFAULT_LAKE_STAGING_ROOT),
    duckdb_resource: DuckDBResource,
    partition_keys: Sequence[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    batch_partition_limit: int = MAX_BATCH_PARTITION_COUNT,
    output_dir: Path = Path("/private/tmp"),
) -> StockDailyQfqNineTurnServingHistoryPlan:
    """Audit and freeze the exact source scope without writing Prod or Lake."""

    _validate_batch_partition_limit(batch_partition_limit)
    normalized_lake_root, normalized_staging_root = _validate_roots(
        lake_root=lake_root,
        staging_root=staging_root,
    )
    selected_keys = _selected_partition_keys(
        lake_root=normalized_lake_root,
        partition_keys=partition_keys,
        start_date=start_date,
        end_date=end_date,
    )
    stop_reasons: list[str] = []
    partitions: list[ServingHistoryPartition] = []
    if not selected_keys:
        stop_reasons.append("empty_partition_scope")
    for key_batch in _partition_batches(selected_keys, batch_partition_limit):
        with duckdb_resource.connect() as connection:
            _configure_history_duckdb(connection)
            for partition_key in key_batch:
                source_path = gold_stock_daily_qfq_nineturn_path(
                    normalized_lake_root,
                    partition_key,
                )
                qfq_path = gold_stock_daily_qfq_path(
                    normalized_lake_root,
                    partition_key,
                )
                if not source_path.is_file():
                    stop_reasons.append(f"{partition_key}:missing_nineturn_source")
                    continue
                if not qfq_path.is_file():
                    stop_reasons.append(f"{partition_key}:missing_qfq_source")
                    continue
                try:
                    diagnostics = audit_gold_stock_daily_qfq_nineturn_for_prod_sync(
                        connection=connection,
                        source_path=source_path,
                        qfq_source_path=qfq_path,
                        partition_key=partition_key,
                    )
                except Exception as error:  # noqa: BLE001 - fail-closed plan.
                    stop_reasons.append(
                        f"{partition_key}:source_contract_failed:{type(error).__name__}"
                    )
                    continue
                source_stat = source_path.stat()
                partitions.append(
                    ServingHistoryPartition(
                        partition_key=partition_key,
                        source_relative_path=_relative_path(
                            source_path,
                            normalized_lake_root,
                        ),
                        source_size=source_stat.st_size,
                        source_mtime_ns=source_stat.st_mtime_ns,
                        row_count=diagnostics.checked_row_count,
                    )
                )
    normalized_partitions = tuple(
        sorted(partitions, key=lambda item: item.partition_key)
    )
    normalized_stop_reasons = tuple(sorted(set(stop_reasons)))
    fingerprint_payload = _fingerprint_payload(
        lake_root=normalized_lake_root,
        staging_root=normalized_staging_root,
        batch_partition_limit=batch_partition_limit,
        partitions=normalized_partitions,
        stop_reasons=normalized_stop_reasons,
    )
    plan_fingerprint = _hash_payload(fingerprint_payload)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / (
        "stock_daily_qfq_nineturn_serving_history_plan_"
        f"{datetime.now(UTC).strftime('%Y%m%d_%H%M%S_%f')}.json"
    )
    report = {
        **fingerprint_payload,
        "phase": PLAN_PHASE,
        "read_only": True,
        "plan_fingerprint": plan_fingerprint,
        "partition_count": len(normalized_partitions),
        "source_row_count": sum(item.row_count for item in normalized_partitions),
        "estimated_batch_count": (
            (len(normalized_partitions) + batch_partition_limit - 1)
            // batch_partition_limit
        ),
        "should_stop": bool(normalized_stop_reasons),
    }
    _write_json_atomic(report_path, report)
    return StockDailyQfqNineTurnServingHistoryPlan(
        report_path=report_path,
        lake_root=normalized_lake_root,
        staging_root=normalized_staging_root,
        plan_fingerprint=plan_fingerprint,
        batch_partition_limit=batch_partition_limit,
        partitions=normalized_partitions,
        stop_reasons=normalized_stop_reasons,
        report=report,
    )


def load_stock_daily_qfq_nineturn_serving_history_plan(
    plan_report_path: Path,
) -> StockDailyQfqNineTurnServingHistoryPlan:
    payload = json.loads(Path(plan_report_path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise StockDailyQfqNineTurnServingHistoryError("Unsupported plan schema.")
    if payload.get("phase") != PLAN_PHASE or payload.get("read_only") is not True:
        raise StockDailyQfqNineTurnServingHistoryError(
            "History publication requires a reviewed read-only plan."
        )
    plan = StockDailyQfqNineTurnServingHistoryPlan(
        report_path=Path(plan_report_path),
        lake_root=Path(str(payload["lake_root"])),
        staging_root=Path(str(payload["staging_root"])),
        plan_fingerprint=str(payload["plan_fingerprint"]),
        batch_partition_limit=int(payload["batch_partition_limit"]),
        partitions=tuple(
            ServingHistoryPartition(**dict(item)) for item in payload["partitions"]
        ),
        stop_reasons=tuple(str(item) for item in payload["stop_reasons"]),
        report=payload,
    )
    if _plan_fingerprint(plan) != plan.plan_fingerprint:
        raise StockDailyQfqNineTurnServingHistoryError(
            "History publication plan fingerprint does not match its content."
        )
    return plan


def publish_stock_daily_qfq_nineturn_serving_history(
    *,
    plan: StockDailyQfqNineTurnServingHistoryPlan,
    expected_plan_fingerprint: str,
    duckdb_resource: DuckDBResource,
    prod_postgres_write: ProdPostgresWriteResource,
    checkpoint_path: Path,
    mode: str = "batch",
    sample_partition_keys: Sequence[str] = (),
    batch_count_limit: int = 1,
    progress_callback: Callable[[Mapping[str, object]], None] | None = None,
) -> StockDailyQfqNineTurnServingHistoryPublishReport:
    """Publish one reviewed sample or one bounded batch, checkpointing each date."""

    if plan.plan_fingerprint != expected_plan_fingerprint:
        raise StockDailyQfqNineTurnServingHistoryError(
            "Explicit plan fingerprint does not match the reviewed plan."
        )
    if plan.should_stop:
        raise StockDailyQfqNineTurnServingHistoryError(
            f"History publication plan is blocked: {plan.stop_reasons}."
        )
    _validate_batch_count_limit(batch_count_limit)
    _validate_frozen_plan_source_identities(plan)
    normalized_checkpoint_path = _validated_checkpoint_path(
        checkpoint_path=checkpoint_path,
        staging_root=plan.staging_root,
    )
    checkpoint = _load_checkpoint(
        normalized_checkpoint_path,
        plan_fingerprint=plan.plan_fingerprint,
    )
    completed = dict(checkpoint.get("completed", {}))
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
                source_path = gold_stock_daily_qfq_nineturn_path(
                    plan.lake_root,
                    partition_key,
                )
                rows = load_gold_stock_daily_qfq_nineturn_rows_with_connection(
                    connection=duckdb_connection,
                    source_path=source_path,
                    qfq_source_path=gold_stock_daily_qfq_path(
                        plan.lake_root,
                        partition_key,
                    ),
                    partition_key=partition_key,
                )
                replace_prod_core_stock_daily_qfq_nineturn_partition(
                    connection=write_connection,
                    rows=rows,
                    partition_key=partition_key,
                )
                write_connection.commit()
                try:
                    audit = audit_prod_core_stock_daily_qfq_nineturn_partition(
                        connection=read_connection,
                        rows=rows,
                        partition_key=partition_key,
                    )
                finally:
                    read_connection.rollback()
                if not audit.passed:
                    raise StockDailyQfqNineTurnServingHistoryError(
                        f"Serving read-back failed after commit for {partition_key}."
                    )
                completed[partition_key] = audit.expected_content_hash
                _write_checkpoint(
                    normalized_checkpoint_path,
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
                        "remaining_partition_count": max(
                            len(plan.partitions) - len(completed),
                            0,
                        ),
                    }
                )
    remaining = len(plan.partitions) - len(completed)
    return StockDailyQfqNineTurnServingHistoryPublishReport(
        plan_fingerprint=plan.plan_fingerprint,
        mode=mode,
        selected_partition_keys=selected,
        published_partition_keys=tuple(published),
        resumed_partition_keys=resumed,
        remaining_partition_count=max(remaining, 0),
        processed_batch_count=(
            (len(selected) + plan.batch_partition_limit - 1)
            // plan.batch_partition_limit
        ),
        checkpoint_path=normalized_checkpoint_path,
        elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
    )


def _selected_partition_keys(
    *,
    lake_root: Path,
    partition_keys: Sequence[str] | None,
    start_date: str | None,
    end_date: str | None,
) -> tuple[str, ...]:
    discovered = tuple(
        sorted(
            path.parent.name.removeprefix("trade_date=")
            for path in (
                lake_root / "gold" / "indicator" / "stock_daily_qfq_nineturn"
            ).glob("trade_date=*/part-000.parquet")
            if path.is_file()
        )
    )
    if partition_keys is not None:
        selected = tuple(sorted({str(item) for item in partition_keys}))
        missing = tuple(item for item in selected if item not in set(discovered))
        if missing:
            raise StockDailyQfqNineTurnServingHistoryError(
                f"Requested Gold partitions are missing: {missing[:20]}."
            )
        return selected
    return tuple(
        item
        for item in discovered
        if (start_date is None or item >= start_date)
        and (end_date is None or item <= end_date)
    )


def _publication_selection(
    *,
    plan: StockDailyQfqNineTurnServingHistoryPlan,
    completed: Mapping[str, object],
    mode: str,
    sample_partition_keys: Sequence[str],
    batch_count_limit: int,
) -> tuple[str, ...]:
    all_keys = tuple(item.partition_key for item in plan.partitions)
    pending = tuple(item for item in all_keys if item not in completed)
    if mode == "batch":
        if sample_partition_keys:
            raise StockDailyQfqNineTurnServingHistoryError(
                "Batch mode does not accept sample partitions."
            )
        return pending[: plan.batch_partition_limit * batch_count_limit]
    if mode != "sample":
        raise StockDailyQfqNineTurnServingHistoryError("Mode must be sample or batch.")
    samples = tuple(dict.fromkeys(str(item) for item in sample_partition_keys))
    if not samples or len(samples) > MAX_SAMPLE_PARTITION_COUNT:
        raise StockDailyQfqNineTurnServingHistoryError(
            "Sample mode requires one to three explicit partitions."
        )
    invalid = tuple(item for item in samples if item not in set(all_keys))
    if invalid:
        raise StockDailyQfqNineTurnServingHistoryError(
            f"Sample partitions are outside the reviewed plan: {invalid}."
        )
    return tuple(item for item in samples if item not in completed)


def _validate_completed_partitions(
    *,
    plan: StockDailyQfqNineTurnServingHistoryPlan,
    completed: Mapping[str, object],
    prod_postgres_write: ProdPostgresWriteResource,
) -> tuple[str, ...]:
    plan_keys = {item.partition_key for item in plan.partitions}
    unknown = tuple(sorted(set(completed) - plan_keys))
    if unknown:
        raise StockDailyQfqNineTurnServingHistoryError(
            f"Checkpoint contains partitions outside the plan: {unknown[:20]}."
        )
    if not completed:
        return ()
    validated: list[str] = []
    with prod_postgres_write.connect_readonly() as connection:
        try:
            audit = audit_prod_core_stock_daily_qfq_nineturn_checkpoint_partitions(
                connection=connection,
                expected_content_hashes=completed,
            )
        finally:
            connection.rollback()
    if not audit.passed:
        raise StockDailyQfqNineTurnServingHistoryError(
            "Checkpoint/serving drift detected for partitions: "
            f"{audit.failed_partition_keys[:20]}."
        )
    validated.extend(sorted(completed))
    return tuple(validated)


def _validate_frozen_plan_source_identities(
    plan: StockDailyQfqNineTurnServingHistoryPlan,
) -> None:
    """Check frozen size/mtime identities without re-reading Parquet content."""

    failures: list[str] = []
    for partition in plan.partitions:
        try:
            source_path = _validated_plan_source_path(
                lake_root=plan.lake_root,
                relative_path=partition.source_relative_path,
            )
            observed = source_path.stat()
        except (OSError, StockDailyQfqNineTurnServingHistoryError):
            failures.append(f"{partition.partition_key}:nineturn:missing")
        else:
            if (
                observed.st_size != partition.source_size
                or observed.st_mtime_ns != partition.source_mtime_ns
            ):
                failures.append(f"{partition.partition_key}:nineturn:changed")
        if len(failures) >= 20:
            break
    if failures:
        raise StockDailyQfqNineTurnServingHistoryError(
            "History publication plan is stale; generate and review a new plan. "
            f"Changed sources: {tuple(failures)}."
        )


def _validated_plan_source_path(*, lake_root: Path, relative_path: str) -> Path:
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise StockDailyQfqNineTurnServingHistoryError(
            "History publication plan contains an unsafe source path."
        )
    normalized_root = lake_root.resolve()
    normalized_source = (normalized_root / relative).resolve(strict=True)
    try:
        normalized_source.relative_to(normalized_root)
    except ValueError as error:
        raise StockDailyQfqNineTurnServingHistoryError(
            "History publication plan source resolves outside the Lake root."
        ) from error
    if not normalized_source.is_file():
        raise StockDailyQfqNineTurnServingHistoryError(
            "History publication plan source is not a file."
        )
    return normalized_source


def _partition_batches(
    items: Sequence[_BatchItemT],
    limit: int,
) -> tuple[tuple[_BatchItemT, ...], ...]:
    return tuple(
        tuple(items[index : index + limit])
        for index in range(0, len(items), limit)
    )


def _partition_key_summary(
    prefix: str,
    partition_keys: Sequence[str],
) -> dict[str, object]:
    return {
        f"{prefix}_partition_count": len(partition_keys),
        f"{prefix}_first_partition_key": partition_keys[0] if partition_keys else None,
        f"{prefix}_last_partition_key": partition_keys[-1] if partition_keys else None,
    }


def _configure_history_duckdb(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    connection.execute(f"SET memory_limit = '{HISTORY_DUCKDB_MEMORY_LIMIT}'")
    connection.execute(f"SET threads = {HISTORY_DUCKDB_THREADS}")
    connection.execute("SET preserve_insertion_order = false")


def _load_checkpoint(path: Path, *, plan_fingerprint: str) -> dict[str, object]:
    if not path.exists():
        return {"completed": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("phase") != CHECKPOINT_PHASE
        or payload.get("plan_fingerprint") != plan_fingerprint
    ):
        raise StockDailyQfqNineTurnServingHistoryError(
            "Checkpoint does not belong to the reviewed publication plan."
        )
    completed = payload.get("completed")
    if not isinstance(completed, dict):
        raise StockDailyQfqNineTurnServingHistoryError("Checkpoint is malformed.")
    return {"completed": {str(key): str(value) for key, value in completed.items()}}


def _write_checkpoint(
    path: Path,
    *,
    plan_fingerprint: str,
    completed: Mapping[str, object],
) -> None:
    _write_json_atomic(
        path,
        {
            "schema_version": SCHEMA_VERSION,
            "phase": CHECKPOINT_PHASE,
            "plan_fingerprint": plan_fingerprint,
            "completed": dict(sorted(completed.items())),
            "completed_partition_count": len(completed),
            "updated_at": datetime.now().astimezone().isoformat(),
        },
    )


def _validated_checkpoint_path(*, checkpoint_path: Path, staging_root: Path) -> Path:
    normalized = Path(checkpoint_path).resolve()
    try:
        normalized.relative_to(staging_root.resolve())
    except ValueError as error:
        raise StockDailyQfqNineTurnServingHistoryError(
            "Checkpoint must be stored below the reviewed staging root."
        ) from error
    return normalized


def _validate_roots(*, lake_root: Path, staging_root: Path) -> tuple[Path, Path]:
    normalized_lake = Path(lake_root).resolve()
    normalized_staging = Path(staging_root).resolve()
    if normalized_lake == Path(DEFAULT_LAKE_ROOT).resolve():
        if normalized_staging != Path(DEFAULT_LAKE_STAGING_ROOT).resolve():
            raise StockDailyQfqNineTurnServingHistoryError(
                "Formal publication must use the fixed data_lake_staging root."
            )
    elif normalized_lake == normalized_staging:
        raise StockDailyQfqNineTurnServingHistoryError(
            "Fixture staging root must be separate from fixture Lake root."
        )
    return normalized_lake, normalized_staging


def _validate_batch_partition_limit(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StockDailyQfqNineTurnServingHistoryError(
            "Batch partition limit must be an integer."
        )
    if value <= 0 or value > MAX_BATCH_PARTITION_COUNT:
        raise StockDailyQfqNineTurnServingHistoryError(
            f"Batch partition limit must be between 1 and {MAX_BATCH_PARTITION_COUNT}."
        )


def _validate_batch_count_limit(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StockDailyQfqNineTurnServingHistoryError(
            "Batch count limit must be an integer."
        )
    if value <= 0 or value > MAX_BATCH_COUNT_PER_RUN:
        raise StockDailyQfqNineTurnServingHistoryError(
            f"Batch count limit must be between 1 and {MAX_BATCH_COUNT_PER_RUN}."
        )


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise StockDailyQfqNineTurnServingHistoryError(
            f"Source path is outside the reviewed Lake root: {path}."
        ) from error


def _fingerprint_payload(
    *,
    lake_root: Path,
    staging_root: Path,
    batch_partition_limit: int,
    partitions: Sequence[ServingHistoryPartition],
    stop_reasons: Sequence[str],
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "lake_root": str(lake_root.resolve()),
        "staging_root": str(staging_root.resolve()),
        "batch_partition_limit": batch_partition_limit,
        "partitions": [item.to_dict() for item in partitions],
        "stop_reasons": list(stop_reasons),
    }


def _plan_fingerprint(plan: StockDailyQfqNineTurnServingHistoryPlan) -> str:
    return _hash_payload(
        _fingerprint_payload(
            lake_root=plan.lake_root,
            staging_root=plan.staging_root,
            batch_partition_limit=plan.batch_partition_limit,
            partitions=plan.partitions,
            stop_reasons=plan.stop_reasons,
        )
    )


def _hash_payload(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
