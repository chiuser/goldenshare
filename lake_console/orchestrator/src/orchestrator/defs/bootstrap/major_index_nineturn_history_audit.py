"""Aggregate final audit for reviewed major-index nine-turn history output."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from orchestrator.defs.bootstrap.major_index_nineturn_history import (
    CHECKPOINT_PHASE,
    MajorIndexNineturnHistoryError,
    MajorIndexNineturnHistoryPlan,
    load_major_index_nineturn_history_plan,
)
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.paths import (
    gold_major_index_daily_nineturn_path,
    gold_major_index_mins_nineturn_path,
)
from orchestrator.defs.run_contracts.major_index_nineturn import (
    MAJOR_INDEX_NINETURN_HISTORY_MEMORY_LIMIT,
    MAJOR_INDEX_NINETURN_HISTORY_THREADS,
)

AUDIT_SCHEMA_VERSION = 1
AUDIT_PHASE = "major_index_nineturn_history_final_audit"


@dataclass(frozen=True, slots=True)
class MajorIndexNineturnAssetHistoryAudit:
    asset_key: str
    freq: int | None
    expected_partition_count: int
    actual_partition_count: int
    expected_row_count: int
    actual_row_count: int
    missing_partition_count: int
    extra_partition_count: int
    duplicate_key_count: int
    null_key_count: int
    partition_mismatch_count: int
    invalid_value_count: int
    missing_source_key_count: int
    extra_target_key_count: int
    source_value_mismatch_count: int
    start_date: str | None
    end_date: str | None
    elapsed_ms: float

    @property
    def passed(self) -> bool:
        return all(
            value == 0
            for value in (
                self.missing_partition_count,
                self.extra_partition_count,
                self.duplicate_key_count,
                self.null_key_count,
                self.partition_mismatch_count,
                self.invalid_value_count,
                self.missing_source_key_count,
                self.extra_target_key_count,
                self.source_value_mismatch_count,
                self.expected_partition_count - self.actual_partition_count,
                self.expected_row_count - self.actual_row_count,
            )
        )

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "freq": self.freq or "daily", "passed": self.passed}


def audit_major_index_nineturn_history(
    *,
    plan_report_path: Path,
    checkpoint_path: Path,
    output_path: Path,
) -> Mapping[str, object]:
    """Audit exact target manifests, checkpoint hashes, and aggregate source parity."""

    started = time.perf_counter()
    plan = load_major_index_nineturn_history_plan(plan_report_path)
    completed = _load_completed_checkpoint(
        checkpoint_path,
        expected_plan_fingerprint=plan.plan_fingerprint,
    )
    expected_batch_keys = {
        f"{batch.asset_key}:{batch.batch_index}" for batch in plan.batches
    }
    stop_reasons: list[str] = []
    if set(completed) != expected_batch_keys:
        stop_reasons.append("checkpoint_batch_set_mismatch")
    checkpoint_hash_mismatches = _checkpoint_hash_mismatches(
        plan=plan,
        completed=completed,
    )
    if checkpoint_hash_mismatches:
        stop_reasons.append("checkpoint_target_hash_mismatch")

    asset_audits = tuple(_audit_asset(plan, asset_key) for asset_key in _asset_keys(plan))
    stop_reasons.extend(
        f"{audit.asset_key}:aggregate_integrity_failed"
        for audit in asset_audits
        if not audit.passed
    )
    unexpected_one_minute_files = tuple(
        sorted(
            (
                plan.lake_root
                / "gold/indicator/major_index_mins_nineturn/freq=1"
            ).glob("trade_date=*/part-000.parquet")
        )
    )
    if unexpected_one_minute_files:
        stop_reasons.append("unexpected_1m_target_files")

    report: dict[str, object] = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "phase": AUDIT_PHASE,
        "read_only": True,
        "plan_report_path": str(Path(plan_report_path).resolve()),
        "plan_fingerprint": plan.plan_fingerprint,
        "checkpoint_path": str(Path(checkpoint_path).resolve()),
        "expected_batch_count": len(expected_batch_keys),
        "completed_batch_count": len(completed),
        "expected_target_file_count": sum(
            audit.expected_partition_count for audit in asset_audits
        ),
        "actual_target_file_count": sum(
            audit.actual_partition_count for audit in asset_audits
        ),
        "expected_row_count": sum(audit.expected_row_count for audit in asset_audits),
        "actual_row_count": sum(audit.actual_row_count for audit in asset_audits),
        "checkpoint_hash_mismatch_count": len(checkpoint_hash_mismatches),
        "checkpoint_hash_mismatch_samples": list(checkpoint_hash_mismatches[:20]),
        "unexpected_1m_target_file_count": len(unexpected_one_minute_files),
        "assets": [audit.to_dict() for audit in asset_audits],
        "physical_fingerprint": _physical_fingerprint(plan),
        "stop_reasons": sorted(set(stop_reasons)),
        "should_stop": bool(stop_reasons),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
    }
    _write_json_atomic(Path(output_path), report)
    return report


def _asset_keys(plan: MajorIndexNineturnHistoryPlan) -> tuple[str, ...]:
    return tuple(dict.fromkeys(batch.asset_key for batch in plan.batches))


def _audit_asset(
    plan: MajorIndexNineturnHistoryPlan,
    asset_key: str,
) -> MajorIndexNineturnAssetHistoryAudit:
    started = time.perf_counter()
    batches = tuple(batch for batch in plan.batches if batch.asset_key == asset_key)
    freq = batches[0].freq
    expected_dates = tuple(date for batch in batches for date in batch.trade_dates)
    expected_targets = tuple(
        _target_path(plan, freq=freq, trade_date=trade_date)
        for trade_date in expected_dates
    )
    target_root = expected_targets[0].parents[1]
    actual_targets = tuple(sorted(target_root.glob("trade_date=*/part-000.parquet")))
    expected_set = {path.resolve() for path in expected_targets}
    actual_set = {path.resolve() for path in actual_targets}
    metrics = {
        "actual_row_count": 0,
        "duplicate_key_count": 0,
        "null_key_count": 0,
        "partition_mismatch_count": 0,
        "invalid_value_count": 0,
        "missing_source_key_count": 0,
        "extra_target_key_count": 0,
        "source_value_mismatch_count": 0,
        "start_date": None,
        "end_date": None,
    }
    settings = DuckDBConnectionSettings(
        memory_limit=MAJOR_INDEX_NINETURN_HISTORY_MEMORY_LIMIT,
        threads=MAJOR_INDEX_NINETURN_HISTORY_THREADS,
        preserve_insertion_order=False,
    )
    for batch in batches:
        batch_targets = tuple(
            _target_path(plan, freq=freq, trade_date=trade_date)
            for trade_date in batch.trade_dates
            if _target_path(plan, freq=freq, trade_date=trade_date).is_file()
        )
        if not batch_targets:
            metrics["missing_source_key_count"] += len(batch.source_paths)
            continue
        with connect_configured_duckdb(settings) as connection:
            batch_metrics = _aggregate_metrics(
                connection=connection,
                target_paths=batch_targets,
                source_paths=batch.source_paths,
                freq=freq,
            )
        for name in (
            "actual_row_count",
            "duplicate_key_count",
            "null_key_count",
            "partition_mismatch_count",
            "invalid_value_count",
            "missing_source_key_count",
            "extra_target_key_count",
            "source_value_mismatch_count",
        ):
            metrics[name] += int(batch_metrics[name])
        if batch_metrics["start_date"] is not None and (
            metrics["start_date"] is None
            or batch_metrics["start_date"] < metrics["start_date"]
        ):
            metrics["start_date"] = batch_metrics["start_date"]
        if batch_metrics["end_date"] is not None and (
            metrics["end_date"] is None
            or batch_metrics["end_date"] > metrics["end_date"]
        ):
            metrics["end_date"] = batch_metrics["end_date"]
    return MajorIndexNineturnAssetHistoryAudit(
        asset_key=asset_key,
        freq=freq,
        expected_partition_count=len(expected_targets),
        actual_partition_count=len(actual_targets),
        expected_row_count=sum(batch.source_row_count for batch in batches),
        actual_row_count=int(metrics["actual_row_count"]),
        missing_partition_count=len(expected_set - actual_set),
        extra_partition_count=len(actual_set - expected_set),
        duplicate_key_count=int(metrics["duplicate_key_count"]),
        null_key_count=int(metrics["null_key_count"]),
        partition_mismatch_count=int(metrics["partition_mismatch_count"]),
        invalid_value_count=int(metrics["invalid_value_count"]),
        missing_source_key_count=int(metrics["missing_source_key_count"]),
        extra_target_key_count=int(metrics["extra_target_key_count"]),
        source_value_mismatch_count=int(metrics["source_value_mismatch_count"]),
        start_date=(str(metrics["start_date"]) if metrics["start_date"] else None),
        end_date=(str(metrics["end_date"]) if metrics["end_date"] else None),
        elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
    )


def _aggregate_metrics(*, connection, target_paths, source_paths, freq):
    target = _read_paths(target_paths, filename=True)
    source = _read_paths(source_paths, filename=False)
    key_columns = (
        "ts_code, trade_date" if freq is None else "ts_code, freq, trade_time"
    )
    join_condition = (
        "source.ts_code = target.ts_code AND source.trade_date = target.trade_date"
        if freq is None
        else "source.ts_code = target.ts_code AND source.freq = target.freq "
        "AND source.trade_time = target.trade_time"
    )
    target_missing_condition = (
        "target.trade_date IS NULL" if freq is None else "target.trade_time IS NULL"
    )
    source_missing_condition = (
        "source.trade_date IS NULL" if freq is None else "source.trade_time IS NULL"
    )
    minute_nulls = "" if freq is None else "OR freq IS NULL OR trade_time IS NULL"
    minute_partition = (
        ""
        if freq is None
        else f"OR freq != {freq} OR CAST(trade_time AS DATE) != trade_date"
    )
    row = connection.execute(
        f"""
        WITH target AS (SELECT * FROM {target}),
        source AS (SELECT * FROM {source}),
        target_metrics AS (
          SELECT
            count(*) AS actual_row_count,
            count(*) - count(DISTINCT ({key_columns})) AS duplicate_key_count,
            count(*) FILTER (
              WHERE ts_code IS NULL OR trim(ts_code) = '' OR trade_date IS NULL
                {minute_nulls}
            ) AS null_key_count,
            count(*) FILTER (
              WHERE trade_date != CAST(regexp_extract(filename, 'trade_date=([0-9-]+)', 1) AS DATE)
                {minute_partition}
            ) AS partition_mismatch_count,
            count(*) FILTER (
              WHERE close IS NULL OR NOT isfinite(close) OR close <= 0
                OR up_count IS NULL OR down_count IS NULL
                OR up_count < 0 OR down_count < 0
                OR (up_count > 0 AND down_count > 0)
                OR (nine_up_turn IS NOT NULL AND nine_up_turn != '+9')
                OR (nine_down_turn IS NOT NULL AND nine_down_turn != '-9')
                OR (nine_up_turn = '+9' AND up_count < 9)
                OR (nine_down_turn = '-9' AND down_count < 9)
                OR (nine_up_turn IS NOT NULL AND nine_down_turn IS NOT NULL)
            ) AS invalid_value_count,
            min(trade_date) AS start_date,
            max(trade_date) AS end_date
          FROM target
        ),
        missing_source AS (
          SELECT count(*) AS value
          FROM source LEFT JOIN target ON {join_condition}
          WHERE {target_missing_condition}
        ),
        extra_target AS (
          SELECT count(*) AS value
          FROM target LEFT JOIN source ON {join_condition}
          WHERE {source_missing_condition}
        ),
        mismatched_values AS (
          SELECT count(*) AS value
          FROM source JOIN target ON {join_condition}
          WHERE source.close IS DISTINCT FROM target.close
        )
        SELECT target_metrics.*, missing_source.value, extra_target.value,
               mismatched_values.value
        FROM target_metrics, missing_source, extra_target, mismatched_values
        """
    ).fetchone()
    names = (
        "actual_row_count",
        "duplicate_key_count",
        "null_key_count",
        "partition_mismatch_count",
        "invalid_value_count",
        "start_date",
        "end_date",
        "missing_source_key_count",
        "extra_target_key_count",
        "source_value_mismatch_count",
    )
    return dict(zip(names, row, strict=True))


def _read_paths(paths: Sequence[Path], *, filename: bool) -> str:
    values = ", ".join(duckdb_string(path) for path in paths)
    return (
        f"read_parquet([{values}], hive_partitioning=false, union_by_name=true, "
        f"filename={'true' if filename else 'false'})"
    )


def _target_path(
    plan: MajorIndexNineturnHistoryPlan, *, freq: int | None, trade_date: str
) -> Path:
    return (
        gold_major_index_daily_nineturn_path(plan.lake_root, trade_date)
        if freq is None
        else gold_major_index_mins_nineturn_path(plan.lake_root, freq, trade_date)
    )


def _load_completed_checkpoint(
    path: Path, *, expected_plan_fingerprint: str
) -> dict[str, Mapping[str, object]]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MajorIndexNineturnHistoryError("History checkpoint is unreadable.") from error
    if (
        payload.get("phase") != CHECKPOINT_PHASE
        or payload.get("plan_fingerprint") != expected_plan_fingerprint
        or not isinstance(payload.get("completed"), Mapping)
    ):
        raise MajorIndexNineturnHistoryError("History checkpoint contract is invalid.")
    return dict(payload["completed"])


def _checkpoint_hash_mismatches(
    *, plan: MajorIndexNineturnHistoryPlan, completed: Mapping[str, Mapping[str, object]]
) -> tuple[str, ...]:
    mismatches: list[str] = []
    for batch in plan.batches:
        batch_key = f"{batch.asset_key}:{batch.batch_index}"
        entry = completed.get(batch_key, {})
        fingerprints = entry.get("target_fingerprints")
        if not isinstance(fingerprints, Mapping):
            mismatches.append(batch_key)
            continue
        for trade_date in batch.trade_dates:
            target = _target_path(plan, freq=batch.freq, trade_date=trade_date)
            if (
                not target.is_file()
                or fingerprints.get(trade_date) != _sha256_path(target)
            ):
                mismatches.append(f"{batch_key}:{trade_date}")
    return tuple(mismatches)


def _physical_fingerprint(plan: MajorIndexNineturnHistoryPlan) -> str:
    digest = hashlib.sha256()
    for batch in plan.batches:
        for trade_date in batch.trade_dates:
            path = _target_path(plan, freq=batch.freq, trade_date=trade_date)
            if path.is_file():
                stat = path.stat()
                relative = path.resolve().relative_to(plan.lake_root).as_posix()
                digest.update(
                    f"{relative}\t{stat.st_size}\t{stat.st_mtime_ns}\n".encode()
                )
    return digest.hexdigest()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


__all__ = [
    "AUDIT_PHASE",
    "MajorIndexNineturnAssetHistoryAudit",
    "audit_major_index_nineturn_history",
]
