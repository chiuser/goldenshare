"""Bounded plan and checkpointed history builder for major-index nine-turn."""

from __future__ import annotations

import hashlib
import json
import os
import resource
import sys
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.major_index_nineturn import (
    build_gold_major_index_nineturn_history_batch_select_sql,
)
from orchestrator.defs.major_index_nineturn_integrity import (
    audit_major_index_nineturn_integrity,
)
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    DEFAULT_LAKE_STAGING_ROOT,
    gold_major_index_daily_nineturn_path,
    gold_major_index_mins_nineturn_path,
)
from orchestrator.defs.run_contracts.major_index_nineturn import (
    MAJOR_INDEX_NINETURN_DAILY_ASSET_KEY,
    MAJOR_INDEX_NINETURN_HISTORY_BATCH_TRADE_DAYS,
    MAJOR_INDEX_NINETURN_HISTORY_MEMORY_LIMIT,
    MAJOR_INDEX_NINETURN_HISTORY_THREADS,
    MAJOR_INDEX_NINETURN_MINUTE_ASSET_KEYS,
    MAJOR_INDEX_NINETURN_MINUTE_FREQS,
)

PLAN_SCHEMA_VERSION = 1
PLAN_PHASE = "major_index_nineturn_history_plan"
CHECKPOINT_PHASE = "major_index_nineturn_history_checkpoint"
MAX_BATCH_SECONDS = 30.0
MAX_PROCESS_RSS_MIB = 512.0


class MajorIndexNineturnHistoryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MajorIndexNineturnHistoryBatch:
    asset_key: str
    freq: int | None
    batch_index: int
    trade_dates: tuple[str, ...]
    source_paths: tuple[Path, ...]
    context_paths: tuple[Path, ...]
    source_identities: tuple[str, ...]
    context_identities: tuple[str, ...]
    source_row_count: int
    source_bytes: int
    existing_target_file_count: int

    @property
    def start_date(self) -> str:
        return self.trade_dates[0]

    @property
    def end_date(self) -> str:
        return self.trade_dates[-1]

    def to_dict(self) -> dict[str, object]:
        return {
            "asset_key": self.asset_key,
            "freq": self.freq if self.freq is not None else "daily",
            "batch_index": self.batch_index,
            "trade_dates": list(self.trade_dates),
            "source_paths": [str(path) for path in self.source_paths],
            "context_paths": [str(path) for path in self.context_paths],
            "source_identities": list(self.source_identities),
            "context_identities": list(self.context_identities),
            "source_row_count": self.source_row_count,
            "source_bytes": self.source_bytes,
            "existing_target_file_count": self.existing_target_file_count,
        }


@dataclass(frozen=True, slots=True)
class MajorIndexNineturnHistoryPlan:
    report_path: Path
    lake_root: Path
    plan_fingerprint: str
    batches: tuple[MajorIndexNineturnHistoryBatch, ...]
    stop_reasons: tuple[str, ...]
    report: Mapping[str, object]

    @property
    def should_stop(self) -> bool:
        return bool(self.stop_reasons)


def plan_major_index_nineturn_history(
    *,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    asset_keys: Sequence[str] | None = None,
    output_dir: Path = Path("/private/tmp"),
) -> MajorIndexNineturnHistoryPlan:
    """Create a read-only, 20-trading-day batch plan; never writes Lake state."""

    started = time.perf_counter()
    root = Path(lake_root).resolve()
    selected = _selected_specs(asset_keys)
    batches: list[MajorIndexNineturnHistoryBatch] = []
    stop_reasons: list[str] = []
    settings = _history_duckdb_settings()
    for asset_key, freq in selected:
        source_paths = _source_paths(root, freq=freq)
        if not source_paths:
            stop_reasons.append(f"{asset_key}:missing_source_files")
            continue
        for batch_index, start in enumerate(
            range(0, len(source_paths), MAJOR_INDEX_NINETURN_HISTORY_BATCH_TRADE_DAYS),
            start=1,
        ):
            selected_paths = source_paths[
                start : start + MAJOR_INDEX_NINETURN_HISTORY_BATCH_TRADE_DAYS
            ]
            context_paths = source_paths[max(0, start - 4) : start]
            trade_dates = tuple(_partition_date(path) for path in selected_paths)
            with connect_configured_duckdb(settings) as connection:
                source_row_count = int(
                    connection.execute(
                        f"SELECT count(*) FROM {_read_paths(selected_paths)}"
                    ).fetchone()[0]
                )
            existing_target_count = sum(
                _target_path(root, freq=freq, trade_date=trade_date).is_file()
                for trade_date in trade_dates
            )
            batch = MajorIndexNineturnHistoryBatch(
                asset_key=asset_key,
                freq=freq,
                batch_index=batch_index,
                trade_dates=trade_dates,
                source_paths=selected_paths,
                context_paths=context_paths,
                source_identities=_file_identities(root, selected_paths),
                context_identities=_file_identities(root, context_paths),
                source_row_count=source_row_count,
                source_bytes=sum(path.stat().st_size for path in selected_paths),
                existing_target_file_count=existing_target_count,
            )
            batches.append(batch)
            if source_row_count <= 0:
                stop_reasons.append(f"{asset_key}:{batch_index}:empty_source_batch")
    normalized = tuple(batches)
    fingerprint_payload = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "phase": PLAN_PHASE,
        "lake_root": str(root),
        "batch_trade_days": MAJOR_INDEX_NINETURN_HISTORY_BATCH_TRADE_DAYS,
        "batches": [batch.to_dict() for batch in normalized],
        "stop_reasons": sorted(set(stop_reasons)),
    }
    fingerprint = _hash_payload(fingerprint_payload)
    report = {
        **fingerprint_payload,
        "read_only": True,
        "plan_fingerprint": fingerprint,
        "asset_count": len(selected),
        "batch_count": len(normalized),
        "source_file_count": sum(len(batch.source_paths) for batch in normalized),
        "source_row_count": sum(batch.source_row_count for batch in normalized),
        "expected_target_file_count": sum(
            len(batch.trade_dates) for batch in normalized
        ),
        "existing_target_file_count": sum(
            batch.existing_target_file_count for batch in normalized
        ),
        "duckdb": {
            "memory_limit": MAJOR_INDEX_NINETURN_HISTORY_MEMORY_LIMIT,
            "threads": MAJOR_INDEX_NINETURN_HISTORY_THREADS,
            "preserve_insertion_order": False,
            "connection_scope": "one_batch",
        },
        "should_stop": bool(stop_reasons),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / (
        "major_index_nineturn_history_plan_"
        f"{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.json"
    )
    _write_json_atomic(report_path, report)
    return MajorIndexNineturnHistoryPlan(
        report_path=report_path,
        lake_root=root,
        plan_fingerprint=fingerprint,
        batches=normalized,
        stop_reasons=tuple(sorted(set(stop_reasons))),
        report=report,
    )


def build_major_index_nineturn_history(
    *,
    plan: MajorIndexNineturnHistoryPlan,
    expected_plan_fingerprint: str,
    confirm_write: bool,
    target_lake_root: Path | None = None,
    staging_root: Path = Path(DEFAULT_LAKE_STAGING_ROOT),
    checkpoint_path: Path,
) -> dict[str, object]:
    """Apply one reviewed plan with per-batch connections and durable checkpoint."""

    if not confirm_write:
        raise MajorIndexNineturnHistoryError(
            "History write requires explicit confirm_write=True."
        )
    if plan.should_stop or plan.plan_fingerprint != expected_plan_fingerprint:
        raise MajorIndexNineturnHistoryError(
            "History plan is stopped or fingerprint mismatched."
        )
    target_root = (
        Path(target_lake_root).resolve()
        if target_lake_root is not None
        else plan.lake_root.resolve()
    )
    staging = Path(staging_root).resolve()
    if staging == plan.lake_root or staging.is_relative_to(plan.lake_root):
        raise MajorIndexNineturnHistoryError(
            "History staging must be outside the formal Lake root."
        )
    completed = _load_checkpoint(
        checkpoint_path,
        expected_plan_fingerprint=expected_plan_fingerprint,
    )
    run_root = staging / "major_index_nineturn_history" / f"run_id={uuid.uuid4()}"
    run_root.mkdir(parents=True, exist_ok=False)
    settings = _history_duckdb_settings()
    processed = 0
    try:
        for batch in plan.batches:
            batch_key = f"{batch.asset_key}:{batch.batch_index}"
            _validate_batch_source_identities(plan.lake_root, batch)
            if batch_key in completed:
                _validate_completed_batch(
                    target_root=target_root,
                    batch=batch,
                    checkpoint_entry=completed[batch_key],
                )
                continue
            started = time.perf_counter()
            previous_target = _previous_target_path(
                target_root=target_root,
                batch=batch,
                all_batches=plan.batches,
            )
            batch_candidate = (
                run_root / batch.asset_key / f"batch={batch.batch_index}.parquet"
            )
            batch_candidate.parent.mkdir(parents=True, exist_ok=True)
            select_sql = build_gold_major_index_nineturn_history_batch_select_sql(
                source_paths=batch.source_paths,
                context_paths=batch.context_paths,
                start_date=batch.start_date,
                end_date=batch.end_date,
                freq=batch.freq,
                previous_partition_path=previous_target,
            )
            with connect_configured_duckdb(settings) as connection:
                connection.execute(copy_query_to_parquet(select_sql, batch_candidate))
                output_rows = int(
                    connection.execute(
                        f"SELECT count(*) FROM {read_parquet(batch_candidate, hive_partitioning=False)}"
                    ).fetchone()[0]
                )
                if output_rows != batch.source_row_count:
                    raise MajorIndexNineturnHistoryError(
                        f"Batch row mismatch for {batch_key}: {output_rows} != {batch.source_row_count}."
                    )
                for trade_date, source_path in zip(
                    batch.trade_dates, batch.source_paths, strict=True
                ):
                    candidate = (
                        run_root
                        / batch.asset_key
                        / f"trade_date={trade_date}"
                        / "part-000.parquet"
                    )
                    candidate.parent.mkdir(parents=True, exist_ok=True)
                    connection.execute(
                        copy_query_to_parquet(
                            f"SELECT * FROM {read_parquet(batch_candidate, hive_partitioning=False)} "
                            f"WHERE trade_date = DATE {duckdb_string(trade_date)}",
                            candidate,
                        )
                    )
                    diagnostics = audit_major_index_nineturn_integrity(
                        connection,
                        target_path=candidate,
                        source_paths=(source_path,),
                        partition_key=trade_date,
                        freq=batch.freq,
                    )
                    if not diagnostics.passed:
                        raise MajorIndexNineturnHistoryError(
                            f"Candidate integrity failed for {batch_key}:{trade_date}: "
                            f"{diagnostics.failed_rule_names}."
                        )
            if time.perf_counter() - started > MAX_BATCH_SECONDS:
                raise MajorIndexNineturnHistoryError(
                    f"Batch exceeded {MAX_BATCH_SECONDS}s: {batch_key}."
                )
            peak_rss_mib = _peak_rss_mib()
            if peak_rss_mib > MAX_PROCESS_RSS_MIB:
                raise MajorIndexNineturnHistoryError(
                    f"Process RSS exceeded {MAX_PROCESS_RSS_MIB:.0f}MiB: "
                    f"{batch_key} observed {peak_rss_mib:.2f}MiB."
                )
            for trade_date in batch.trade_dates:
                candidate = (
                    run_root
                    / batch.asset_key
                    / f"trade_date={trade_date}"
                    / "part-000.parquet"
                )
                target = _target_path(
                    target_root, freq=batch.freq, trade_date=trade_date
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(candidate, target)
            target_fingerprints = {
                trade_date: _file_sha256(
                    _target_path(
                        target_root,
                        freq=batch.freq,
                        trade_date=trade_date,
                    )
                )
                for trade_date in batch.trade_dates
            }
            completed[batch_key] = {
                "completed_at": datetime.now(UTC).isoformat(),
                "source_row_count": batch.source_row_count,
                "target_file_count": len(batch.trade_dates),
                "target_fingerprints": target_fingerprints,
            }
            _write_checkpoint(
                checkpoint_path,
                plan_fingerprint=expected_plan_fingerprint,
                completed=completed,
            )
            processed += 1
    finally:
        _remove_empty_tree(run_root)
    return {
        "plan_fingerprint": expected_plan_fingerprint,
        "processed_batch_count": processed,
        "completed_batch_count": len(completed),
        "checkpoint_path": str(checkpoint_path),
    }


def _selected_specs(
    asset_keys: Sequence[str] | None,
) -> tuple[tuple[str, int | None], ...]:
    specs = (
        (MAJOR_INDEX_NINETURN_DAILY_ASSET_KEY, None),
        *tuple(
            zip(
                MAJOR_INDEX_NINETURN_MINUTE_ASSET_KEYS,
                MAJOR_INDEX_NINETURN_MINUTE_FREQS,
                strict=True,
            )
        ),
    )
    if asset_keys is None:
        return specs
    requested = tuple(dict.fromkeys(str(value) for value in asset_keys))
    known = {asset_key for asset_key, _freq in specs}
    unknown = tuple(value for value in requested if value not in known)
    if unknown:
        raise MajorIndexNineturnHistoryError(f"Unknown asset keys: {unknown}.")
    return tuple(spec for spec in specs if spec[0] in requested)


def _source_paths(lake_root: Path, *, freq: int | None) -> tuple[Path, ...]:
    root = (
        lake_root / "gold" / "market" / "major_indices_daily"
        if freq is None
        else lake_root / "gold" / "quote" / "major_index_mins" / f"freq={freq}"
    )
    return tuple(sorted(root.glob("trade_date=*/part-000.parquet")))


def _target_path(lake_root: Path, *, freq: int | None, trade_date: str) -> Path:
    return (
        gold_major_index_daily_nineturn_path(lake_root, trade_date)
        if freq is None
        else gold_major_index_mins_nineturn_path(lake_root, freq, trade_date)
    )


def _previous_target_path(
    *,
    target_root: Path,
    batch: MajorIndexNineturnHistoryBatch,
    all_batches: Sequence[MajorIndexNineturnHistoryBatch],
) -> Path | None:
    prior_dates = tuple(
        trade_date
        for item in all_batches
        if item.asset_key == batch.asset_key and item.batch_index < batch.batch_index
        for trade_date in item.trade_dates
    )
    if not prior_dates:
        return None
    path = _target_path(target_root, freq=batch.freq, trade_date=prior_dates[-1])
    if not path.is_file():
        raise MajorIndexNineturnHistoryError(
            f"Previous batch seed partition is missing: {path}."
        )
    return path


def _history_duckdb_settings() -> DuckDBConnectionSettings:
    return DuckDBConnectionSettings(
        memory_limit=MAJOR_INDEX_NINETURN_HISTORY_MEMORY_LIMIT,
        threads=MAJOR_INDEX_NINETURN_HISTORY_THREADS,
        preserve_insertion_order=False,
    )


def _file_identities(lake_root: Path, paths: Sequence[Path]) -> tuple[str, ...]:
    root = lake_root.resolve()
    identities: list[str] = []
    for path in paths:
        if path.is_symlink():
            raise MajorIndexNineturnHistoryError(
                f"History source must not be a symlink: {path}."
            )
        resolved = path.resolve()
        if not resolved.is_file() or not resolved.is_relative_to(root):
            raise MajorIndexNineturnHistoryError(
                f"History source must be a file under the reviewed Lake root: {path}."
            )
        stat = resolved.stat()
        identities.append(
            f"{resolved.relative_to(root).as_posix()}\t{stat.st_size}\t{stat.st_mtime_ns}"
        )
    return tuple(identities)


def _validate_batch_source_identities(
    lake_root: Path,
    batch: MajorIndexNineturnHistoryBatch,
) -> None:
    if _file_identities(lake_root, batch.source_paths) != batch.source_identities:
        raise MajorIndexNineturnHistoryError(
            f"Reviewed source files changed for {batch.asset_key}:{batch.batch_index}."
        )
    if _file_identities(lake_root, batch.context_paths) != batch.context_identities:
        raise MajorIndexNineturnHistoryError(
            f"Reviewed context files changed for {batch.asset_key}:{batch.batch_index}."
        )


def _validate_completed_batch(
    *,
    target_root: Path,
    batch: MajorIndexNineturnHistoryBatch,
    checkpoint_entry: Mapping[str, object],
) -> None:
    fingerprints = checkpoint_entry.get("target_fingerprints")
    if not isinstance(fingerprints, dict) or set(fingerprints) != set(
        batch.trade_dates
    ):
        raise MajorIndexNineturnHistoryError(
            f"Checkpoint target manifest is invalid for {batch.asset_key}:{batch.batch_index}."
        )
    for trade_date in batch.trade_dates:
        target = _target_path(target_root, freq=batch.freq, trade_date=trade_date)
        if not target.is_file() or _file_sha256(target) != fingerprints[trade_date]:
            raise MajorIndexNineturnHistoryError(
                f"Completed target changed for {batch.asset_key}:{batch.batch_index}:{trade_date}."
            )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _partition_date(path: Path) -> str:
    return path.parent.name.removeprefix("trade_date=")


def _read_paths(paths: Sequence[Path]) -> str:
    if len(paths) == 1:
        return read_parquet(paths[0], hive_partitioning=False)
    values = ", ".join(duckdb_string(path) for path in paths)
    return f"read_parquet([{values}], hive_partitioning=false, union_by_name=true)"


def _hash_payload(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _load_checkpoint(
    path: Path,
    *,
    expected_plan_fingerprint: str,
) -> dict[str, dict[str, object]]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        payload.get("phase") != CHECKPOINT_PHASE
        or payload.get("plan_fingerprint") != expected_plan_fingerprint
    ):
        raise MajorIndexNineturnHistoryError(
            "Checkpoint does not match the reviewed plan."
        )
    return dict(payload.get("completed", {}))


def _write_checkpoint(
    path: Path,
    *,
    plan_fingerprint: str,
    completed: Mapping[str, object],
) -> None:
    _write_json_atomic(
        path,
        {
            "schema_version": PLAN_SCHEMA_VERSION,
            "phase": CHECKPOINT_PHASE,
            "plan_fingerprint": plan_fingerprint,
            "completed": dict(sorted(completed.items())),
            "updated_at": datetime.now(UTC).isoformat(),
        },
    )


def _write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _remove_empty_tree(path: Path) -> None:
    if not path.exists():
        return
    for child in sorted(path.rglob("*"), reverse=True):
        if child.is_file():
            child.unlink()
        elif child.is_dir():
            child.rmdir()
    path.rmdir()


def _peak_rss_mib() -> float:
    raw = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return raw / (1024 * 1024) if sys.platform == "darwin" else raw / 1024


__all__ = [
    "MajorIndexNineturnHistoryBatch",
    "MajorIndexNineturnHistoryError",
    "MajorIndexNineturnHistoryPlan",
    "build_major_index_nineturn_history",
    "plan_major_index_nineturn_history",
]
