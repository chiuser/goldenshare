"""Offline planning and controlled history writes for QFQ nine-turn assets."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb

from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    describe_parquet_query,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    DEFAULT_LAKE_STAGING_ROOT,
    gold_stk_mins_qfq_nineturn_path,
    gold_stock_daily_qfq_nineturn_path,
    gold_stock_daily_qfq_path,
)
from orchestrator.defs.qfq_nineturn import (
    build_gold_stk_mins_qfq_nineturn_history_batch_select_sql,
    build_gold_stk_mins_qfq_nineturn_select_sql,
    build_gold_stock_daily_qfq_nineturn_history_batch_select_sql,
    build_gold_stock_daily_qfq_nineturn_select_sql,
)
from orchestrator.defs.qfq_nineturn_integrity import audit_qfq_nineturn_integrity
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STK_MINS_QFQ_NINETURN_SCHEMA,
    GOLD_STOCK_DAILY_QFQ_NINETURN_SCHEMA,
)
from orchestrator.defs.run_contracts.column_schema import ColumnContract
from orchestrator.defs.run_contracts.qfq_nineturn import (
    QFQ_NINETURN_COMPARISON_LAG,
    QFQ_NINETURN_MINUTE_FREQS,
)

SCHEMA_VERSION = 1
PLAN_PHASE = "qfq_nineturn_history_plan"
SCOPED_PLAN_PHASE = "qfq_nineturn_scoped_rebuild_plan"
BUILD_METHOD = "annual_set_based_compact_state"
ESTIMATED_OUTPUT_BYTES_PER_ROW = 5
MAX_REPORT_SAMPLES = 20
MAX_SCOPED_REBUILD_BATCH_PARTITION_COUNT = 20
MAX_SCOPED_REBUILD_SAMPLE_PARTITION_COUNT = 3
MAX_SCOPED_REBUILD_BATCH_COUNT_PER_RUN = 200
SCOPED_REBUILD_CHECKPOINT_PHASE = "qfq_nineturn_scoped_rebuild_checkpoint"


class QfqNineturnHistoryError(RuntimeError):
    """Raised when a QFQ nine-turn offline history gate fails."""


@dataclass(frozen=True, slots=True)
class QfqNineturnHistoryBatch:
    asset_key: str
    freq: int | None
    year: int
    source_paths: tuple[Path, ...]
    source_file_count: int
    source_row_count: int
    source_bytes: int
    source_fingerprint: str
    trade_dates: tuple[str, ...]
    stock_code_count: int
    null_key_count: int
    duplicate_key_count: int
    wrong_year_count: int
    wrong_freq_count: int
    existing_target_file_count: int

    @property
    def start_date(self) -> str:
        return self.trade_dates[0]

    @property
    def end_date(self) -> str:
        return self.trade_dates[-1]

    @property
    def expected_target_file_count(self) -> int:
        return len(self.trade_dates)

    @property
    def estimated_output_bytes(self) -> int:
        return self.source_row_count * ESTIMATED_OUTPUT_BYTES_PER_ROW

    @property
    def failed(self) -> bool:
        return bool(
            not self.source_paths
            or not self.trade_dates
            or self.source_row_count <= 0
            or self.null_key_count
            or self.duplicate_key_count
            or self.wrong_year_count
            or self.wrong_freq_count
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "asset_key": self.asset_key,
            "freq": self.freq if self.freq is not None else "daily",
            "year": self.year,
            "source_file_count": self.source_file_count,
            "source_row_count": self.source_row_count,
            "source_bytes": self.source_bytes,
            "source_fingerprint": self.source_fingerprint,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "trade_dates": list(self.trade_dates),
            "trade_date_count": len(self.trade_dates),
            "stock_code_count": self.stock_code_count,
            "null_key_count": self.null_key_count,
            "duplicate_key_count": self.duplicate_key_count,
            "wrong_year_count": self.wrong_year_count,
            "wrong_freq_count": self.wrong_freq_count,
            "expected_target_file_count": self.expected_target_file_count,
            "existing_target_file_count": self.existing_target_file_count,
            "estimated_output_bytes": self.estimated_output_bytes,
            "estimated_staging_bytes": self.estimated_output_bytes,
        }


@dataclass(frozen=True, slots=True)
class QfqNineturnHistoryPlan:
    report_path: Path
    lake_root: Path
    plan_fingerprint: str
    batches: tuple[QfqNineturnHistoryBatch, ...]
    latest_check_dates_by_asset: Mapping[str, tuple[str, ...]]
    stop_reasons: tuple[str, ...]
    report: Mapping[str, object]

    @property
    def should_stop(self) -> bool:
        return bool(self.stop_reasons)


@dataclass(frozen=True, slots=True)
class QfqNineturnHistoryBatchResult:
    asset_key: str
    freq: int | None
    year: int
    source_row_count: int
    output_row_count: int
    target_file_count: int
    promoted_file_count: int
    reused_file_count: int
    context_row_count: int
    seed_row_count: int
    elapsed_ms: float

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["freq"] = self.freq if self.freq is not None else "daily"
        return payload


@dataclass(frozen=True, slots=True)
class QfqNineturnHistoryBuildReport:
    plan_fingerprint: str
    run_id: str
    batch_results: tuple[QfqNineturnHistoryBatchResult, ...]
    final_audit_report_path: Path
    elapsed_ms: float

    @property
    def promoted_file_count(self) -> int:
        return sum(result.promoted_file_count for result in self.batch_results)

    def to_dict(self) -> dict[str, object]:
        return {
            "plan_fingerprint": self.plan_fingerprint,
            "run_id": self.run_id,
            "batch_results": [result.to_dict() for result in self.batch_results],
            "promoted_file_count": self.promoted_file_count,
            "final_audit_report_path": str(self.final_audit_report_path),
            "elapsed_ms": self.elapsed_ms,
        }


@dataclass(frozen=True, slots=True)
class QfqNineturnScopedRebuildReport:
    asset_keys: tuple[str, ...]
    stock_codes: tuple[str, ...]
    start_date: str
    end_date: str
    mode: str
    selected_partition_keys: tuple[str, ...]
    resumed_partition_keys: tuple[str, ...]
    replaced_partition_count: int
    remaining_partition_count: int
    processed_batch_count: int
    checkpoint_path: Path
    backup_root: Path
    backup_manifest_path: Path
    elapsed_ms: float

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["asset_keys"] = list(self.asset_keys)
        payload["stock_codes"] = list(self.stock_codes)
        payload["selected_partition_keys"] = list(self.selected_partition_keys)
        payload["resumed_partition_keys"] = list(self.resumed_partition_keys)
        payload["checkpoint_path"] = str(self.checkpoint_path)
        payload["backup_root"] = str(self.backup_root)
        payload["backup_manifest_path"] = str(self.backup_manifest_path)
        return payload


@dataclass(frozen=True, slots=True)
class QfqNineturnScopedRebuildPlan:
    report_path: Path
    lake_root: Path
    staging_root: Path
    history_plan_path: Path
    history_plan_fingerprint: str
    plan_fingerprint: str
    asset_family: str
    freqs: tuple[int, ...]
    stock_codes: tuple[str, ...]
    start_date: str
    end_date: str
    batch_partition_limit: int
    target_dates_by_asset: Mapping[str, tuple[str, ...]]
    target_identities: tuple[Mapping[str, object], ...]
    stop_reasons: tuple[str, ...]
    report: Mapping[str, object]

    @property
    def should_stop(self) -> bool:
        return bool(self.stop_reasons)


@dataclass(frozen=True, slots=True)
class _AssetSpec:
    asset_key: str
    freq: int | None
    schema: tuple[ColumnContract, ...]


def plan_qfq_nineturn_history(
    *,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    duckdb_resource: DuckDBResource | None = None,
    asset_keys: Sequence[str] | None = None,
    output_dir: Path = Path("/private/tmp"),
) -> QfqNineturnHistoryPlan:
    """Profile the requested source batches without writing Lake or Dagster state."""

    started = time.perf_counter()
    root = Path(lake_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    resource = duckdb_resource or DuckDBResource()
    selected_specs = _selected_asset_specs(asset_keys)
    batches: list[QfqNineturnHistoryBatch] = []
    stop_reasons: list[str] = []
    dates_by_asset: dict[str, set[str]] = {
        spec.asset_key: set() for spec in selected_specs
    }
    with resource.connect() as connection:
        for spec in selected_specs:
            source_paths_by_year = _source_paths_by_year(root, spec)
            if not source_paths_by_year:
                stop_reasons.append(f"{spec.asset_key}:missing_source_files")
                continue
            for year, source_paths in sorted(source_paths_by_year.items()):
                batch = _profile_batch(
                    connection,
                    lake_root=root,
                    spec=spec,
                    year=year,
                    source_paths=source_paths,
                )
                batches.append(batch)
                dates_by_asset[spec.asset_key].update(batch.trade_dates)
                if batch.failed:
                    stop_reasons.append(
                        f"{spec.asset_key}:{year}:source_contract_failed"
                    )

    normalized_batches = tuple(sorted(batches, key=_batch_sort_key))
    latest_dates = {
        asset_key: tuple(sorted(values)[-20:])
        for asset_key, values in dates_by_asset.items()
    }
    fingerprint_payload = _plan_payload(
        lake_root=root,
        batches=normalized_batches,
        latest_dates=latest_dates,
        stop_reasons=stop_reasons,
    )
    fingerprint = _hash_payload(fingerprint_payload)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    report_path = output_dir / f"qfq_nineturn_history_plan_{timestamp}.json"
    report = {
        "schema_version": SCHEMA_VERSION,
        "phase": PLAN_PHASE,
        "read_only": True,
        "build_method": BUILD_METHOD,
        "lake_root": str(root.resolve()),
        "asset_count": len(selected_specs),
        "batch_count": len(normalized_batches),
        "batches": [batch.to_dict() for batch in normalized_batches],
        "source_file_count": sum(
            batch.source_file_count for batch in normalized_batches
        ),
        "source_row_count": sum(batch.source_row_count for batch in normalized_batches),
        "source_bytes": sum(batch.source_bytes for batch in normalized_batches),
        "expected_output_row_count": sum(
            batch.source_row_count for batch in normalized_batches
        ),
        "expected_target_file_count": sum(
            batch.expected_target_file_count for batch in normalized_batches
        ),
        "existing_target_file_count": sum(
            batch.existing_target_file_count for batch in normalized_batches
        ),
        "estimated_output_bytes": sum(
            batch.estimated_output_bytes for batch in normalized_batches
        ),
        "estimated_staging_bytes": sum(
            batch.estimated_output_bytes for batch in normalized_batches
        ),
        "compact_state_row_upper_bound_per_batch": (
            max((batch.stock_code_count for batch in normalized_batches), default=0)
            * (QFQ_NINETURN_COMPARISON_LAG + 1)
        ),
        "latest_check_dates_by_asset": {
            key: list(value) for key, value in sorted(latest_dates.items())
        },
        "should_stop": bool(stop_reasons),
        "stop_reasons": sorted(set(stop_reasons)),
        "plan_fingerprint": fingerprint,
        "performance": {
            "source_business_rows_scanned": sum(
                batch.source_row_count for batch in normalized_batches
            ),
            "historical_rescan_multiplier": 1,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        },
    }
    _write_json(report_path, report)
    return QfqNineturnHistoryPlan(
        report_path=report_path,
        lake_root=root,
        plan_fingerprint=fingerprint,
        batches=normalized_batches,
        latest_check_dates_by_asset=latest_dates,
        stop_reasons=tuple(sorted(set(stop_reasons))),
        report=report,
    )


def load_qfq_nineturn_history_plan(
    plan_report_path: Path,
) -> QfqNineturnHistoryPlan:
    payload = json.loads(Path(plan_report_path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise QfqNineturnHistoryError("Unsupported QFQ nine-turn history plan schema.")
    if payload.get("phase") != PLAN_PHASE or payload.get("read_only") is not True:
        raise QfqNineturnHistoryError("History build requires a read-only P4 plan.")
    if payload.get("should_stop"):
        raise QfqNineturnHistoryError(
            f"History plan has stop reasons: {payload.get('stop_reasons', [])}."
        )
    lake_root = Path(str(payload["lake_root"]))
    batches = tuple(
        _batch_from_payload(item, lake_root=lake_root)
        for item in payload.get("batches", ())
    )
    latest_dates = {
        str(key): tuple(str(value) for value in values)
        for key, values in dict(payload["latest_check_dates_by_asset"]).items()
    }
    plan = QfqNineturnHistoryPlan(
        report_path=Path(plan_report_path),
        lake_root=lake_root,
        plan_fingerprint=str(payload["plan_fingerprint"]),
        batches=batches,
        latest_check_dates_by_asset=latest_dates,
        stop_reasons=(),
        report=payload,
    )
    if _plan_fingerprint(plan) != plan.plan_fingerprint:
        raise QfqNineturnHistoryError(
            "History plan fingerprint does not match its content."
        )
    return plan


def build_qfq_nineturn_history(
    *,
    plan: QfqNineturnHistoryPlan,
    expected_plan_fingerprint: str,
    duckdb_resource: DuckDBResource,
    staging_root: Path = Path(DEFAULT_LAKE_STAGING_ROOT),
    output_dir: Path = Path("/private/tmp"),
) -> QfqNineturnHistoryBuildReport:
    """Apply a fresh history plan using annual set-based batches."""

    if plan.plan_fingerprint != expected_plan_fingerprint:
        raise QfqNineturnHistoryError(
            "Explicit plan fingerprint does not match the plan."
        )
    fresh_plan = plan_qfq_nineturn_history(
        lake_root=plan.lake_root,
        duckdb_resource=duckdb_resource,
        output_dir=output_dir,
    )
    if fresh_plan.plan_fingerprint != plan.plan_fingerprint or tuple(
        batch.to_dict() for batch in fresh_plan.batches
    ) != tuple(batch.to_dict() for batch in plan.batches):
        raise QfqNineturnHistoryError(
            "History plan is stale; regenerate and review a new read-only plan."
        )
    if fresh_plan.should_stop:
        raise QfqNineturnHistoryError(
            f"Fresh history plan failed: {fresh_plan.stop_reasons}."
        )

    started = time.perf_counter()
    output_dir.mkdir(parents=True, exist_ok=True)
    normalized_staging_root = _validated_staging_root(
        lake_root=plan.lake_root,
        staging_root=staging_root,
    )
    run_id = str(uuid.uuid4())
    staging_root = normalized_staging_root / "qfq_nineturn_history" / f"run_id={run_id}"
    staging_root.mkdir(parents=True, exist_ok=False)
    results: list[QfqNineturnHistoryBatchResult] = []
    state_by_asset: dict[str, tuple[Path | None, Path | None]] = {}
    final_audit: dict[str, object] | None = None
    try:
        with duckdb_resource.connect() as connection:
            for index, batch in enumerate(plan.batches, start=1):
                context_path, seed_path = state_by_asset.get(
                    batch.asset_key, (None, None)
                )
                result, next_context, next_seed = _build_history_batch(
                    connection,
                    lake_root=plan.lake_root,
                    staging_root=staging_root,
                    batch=batch,
                    context_path=context_path,
                    seed_path=seed_path,
                )
                results.append(result)
                state_by_asset[batch.asset_key] = (next_context, next_seed)
                _write_json(
                    output_dir / f"qfq_nineturn_history_progress_{index:03d}.json",
                    {
                        "run_id": run_id,
                        "plan_fingerprint": plan.plan_fingerprint,
                        "batch_index": index,
                        "batch_count": len(plan.batches),
                        "batch_result": result.to_dict(),
                    },
                )
        final_audit = audit_qfq_nineturn_history(
            plan=plan,
            duckdb_resource=duckdb_resource,
            output_dir=output_dir,
        )
        if final_audit["should_stop"]:
            raise QfqNineturnHistoryError(
                f"Final history audit failed: {final_audit['stop_reasons']}."
            )
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)

    if final_audit is None:
        raise QfqNineturnHistoryError("History build did not produce a final audit.")
    final_audit_path = Path(str(final_audit["report_path"]))
    return QfqNineturnHistoryBuildReport(
        plan_fingerprint=plan.plan_fingerprint,
        run_id=run_id,
        batch_results=tuple(results),
        final_audit_report_path=final_audit_path,
        elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
    )


def audit_qfq_nineturn_history(
    *,
    plan: QfqNineturnHistoryPlan,
    duckdb_resource: DuckDBResource,
    output_dir: Path = Path("/private/tmp"),
) -> dict[str, object]:
    """Verify file counts, schemas, keys and source/output row equality."""

    started = time.perf_counter()
    stop_reasons: list[str] = []
    asset_reports: list[dict[str, object]] = []
    with duckdb_resource.connect() as connection:
        for spec in _asset_specs():
            batches = tuple(
                batch for batch in plan.batches if batch.asset_key == spec.asset_key
            )
            expected_dates = tuple(
                date_key for batch in batches for date_key in batch.trade_dates
            )
            target_paths = tuple(
                _target_path(plan.lake_root, spec, date_key)
                for date_key in expected_dates
            )
            missing = tuple(
                date_key
                for date_key, path in zip(expected_dates, target_paths, strict=True)
                if not path.is_file()
            )
            existing = tuple(path for path in target_paths if path.is_file())
            output_rows = _count_rows(connection, existing)
            schema_failed = tuple(
                str(path)
                for path in existing
                if not _schema_matches(connection, path, spec.schema)
            )
            duplicate_count, null_count, wrong_date_count, wrong_freq_count = (
                _target_contract_counts(connection, existing, spec)
            )
            source_rows = sum(batch.source_row_count for batch in batches)
            if missing:
                stop_reasons.append(f"{spec.asset_key}:missing_target_files")
            if output_rows != source_rows:
                stop_reasons.append(f"{spec.asset_key}:row_count_mismatch")
            if schema_failed:
                stop_reasons.append(f"{spec.asset_key}:schema_mismatch")
            if duplicate_count or null_count or wrong_date_count or wrong_freq_count:
                stop_reasons.append(f"{spec.asset_key}:target_contract_failed")
            asset_reports.append(
                {
                    "asset_key": spec.asset_key,
                    "freq": spec.freq if spec.freq is not None else "daily",
                    "expected_file_count": len(expected_dates),
                    "existing_file_count": len(existing),
                    "missing_file_count": len(missing),
                    "missing_file_samples": list(missing[:MAX_REPORT_SAMPLES]),
                    "source_row_count": source_rows,
                    "output_row_count": output_rows,
                    "schema_failed_count": len(schema_failed),
                    "schema_failed_samples": list(schema_failed[:MAX_REPORT_SAMPLES]),
                    "duplicate_key_count": duplicate_count,
                    "null_key_count": null_count,
                    "partition_date_mismatch_count": wrong_date_count,
                    "freq_mismatch_count": wrong_freq_count,
                }
            )
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    report_path = output_dir / f"qfq_nineturn_history_final_audit_{timestamp}.json"
    report: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "phase": "qfq_nineturn_history_final_audit",
        "plan_fingerprint": plan.plan_fingerprint,
        "asset_reports": asset_reports,
        "should_stop": bool(stop_reasons),
        "stop_reasons": sorted(set(stop_reasons)),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        "report_path": str(report_path),
    }
    _write_json(report_path, report)
    return report


def plan_qfq_nineturn_scoped_rebuild(
    *,
    lake_root: Path,
    staging_root: Path = Path(DEFAULT_LAKE_STAGING_ROOT),
    duckdb_resource: DuckDBResource,
    asset_family: str,
    freqs: Sequence[int] = (),
    stock_codes: Sequence[str],
    start_date: str,
    end_date: str,
    batch_partition_limit: int = MAX_SCOPED_REBUILD_BATCH_PARTITION_COUNT,
    output_dir: Path = Path("/private/tmp"),
) -> QfqNineturnScopedRebuildPlan:
    """Freeze the exact code/date/file scope before any scoped replacement."""

    normalized_codes = _normalize_stock_codes(stock_codes)
    if not normalized_codes:
        raise QfqNineturnHistoryError(
            "Scoped rebuild requires at least one stock code."
        )
    _validate_date_range(start_date, end_date)
    _validate_scoped_rebuild_batch_partition_limit(batch_partition_limit)
    specs = _scoped_specs(asset_family=asset_family, freqs=freqs)
    normalized_staging_root = _validated_staging_root(
        lake_root=lake_root,
        staging_root=staging_root,
    )
    history_plan = plan_qfq_nineturn_history(
        lake_root=lake_root,
        duckdb_resource=duckdb_resource,
        asset_keys=tuple(spec.asset_key for spec in specs),
        output_dir=output_dir,
    )
    stop_reasons = list(history_plan.stop_reasons)
    target_dates_by_asset: dict[str, tuple[str, ...]] = {}
    target_identities: list[dict[str, object]] = []
    for spec in specs:
        dates = tuple(
            partition_key
            for batch in history_plan.batches
            if batch.asset_key == spec.asset_key
            for partition_key in batch.trade_dates
            if start_date <= partition_key <= end_date
        )
        target_dates_by_asset[spec.asset_key] = dates
        if not dates:
            stop_reasons.append(f"{spec.asset_key}:empty_rebuild_date_scope")
        for partition_key in dates:
            path = _target_path(lake_root, spec, partition_key)
            if not path.is_file():
                stop_reasons.append(
                    f"{spec.asset_key}:{partition_key}:missing_rebuild_target"
                )
                continue
            stat = path.stat()
            target_identities.append(
                {
                    "asset_key": spec.asset_key,
                    "partition_key": partition_key,
                    "relative_path": path.resolve()
                    .relative_to(lake_root.resolve())
                    .as_posix(),
                    "size": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                }
            )
    fingerprint_payload = {
        "schema_version": SCHEMA_VERSION,
        "phase": SCOPED_PLAN_PHASE,
        "history_plan_fingerprint": history_plan.plan_fingerprint,
        "staging_root": str(normalized_staging_root),
        "asset_family": asset_family,
        "freqs": [spec.freq for spec in specs if spec.freq is not None],
        "stock_codes": list(normalized_codes),
        "start_date": start_date,
        "end_date": end_date,
        "batch_partition_limit": batch_partition_limit,
        "target_dates_by_asset": {
            key: list(value) for key, value in sorted(target_dates_by_asset.items())
        },
        "target_identities": target_identities,
        "stop_reasons": sorted(set(stop_reasons)),
    }
    fingerprint = _hash_payload(fingerprint_payload)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    report_path = output_dir / f"qfq_nineturn_scoped_rebuild_plan_{timestamp}.json"
    report = {
        **fingerprint_payload,
        "read_only": True,
        "lake_root": str(lake_root.resolve()),
        "history_plan_path": str(history_plan.report_path),
        "target_partition_count": sum(
            len(values) for values in target_dates_by_asset.values()
        ),
        "target_bytes": sum(int(item["size"]) for item in target_identities),
        "estimated_backup_bytes": sum(int(item["size"]) for item in target_identities),
        "estimated_batch_count": (
            (
                sum(len(values) for values in target_dates_by_asset.values())
                + batch_partition_limit
                - 1
            )
            // batch_partition_limit
        ),
        "should_stop": bool(stop_reasons),
        "plan_fingerprint": fingerprint,
    }
    _write_json(report_path, report)
    return QfqNineturnScopedRebuildPlan(
        report_path=report_path,
        lake_root=lake_root,
        staging_root=normalized_staging_root,
        history_plan_path=history_plan.report_path,
        history_plan_fingerprint=history_plan.plan_fingerprint,
        plan_fingerprint=fingerprint,
        asset_family=asset_family,
        freqs=tuple(spec.freq for spec in specs if spec.freq is not None),
        stock_codes=normalized_codes,
        start_date=start_date,
        end_date=end_date,
        batch_partition_limit=batch_partition_limit,
        target_dates_by_asset=target_dates_by_asset,
        target_identities=tuple(target_identities),
        stop_reasons=tuple(sorted(set(stop_reasons))),
        report=report,
    )


def load_qfq_nineturn_scoped_rebuild_plan(
    plan_report_path: Path,
) -> QfqNineturnScopedRebuildPlan:
    payload = json.loads(Path(plan_report_path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise QfqNineturnHistoryError("Unsupported scoped rebuild plan schema.")
    if (
        payload.get("phase") != SCOPED_PLAN_PHASE
        or payload.get("read_only") is not True
    ):
        raise QfqNineturnHistoryError("Scoped rebuild requires a read-only scope plan.")
    if payload.get("should_stop"):
        raise QfqNineturnHistoryError(
            f"Scoped rebuild plan has stop reasons: {payload.get('stop_reasons', [])}."
        )
    plan = QfqNineturnScopedRebuildPlan(
        report_path=Path(plan_report_path),
        lake_root=Path(str(payload["lake_root"])),
        staging_root=Path(str(payload["staging_root"])),
        history_plan_path=Path(str(payload["history_plan_path"])),
        history_plan_fingerprint=str(payload["history_plan_fingerprint"]),
        plan_fingerprint=str(payload["plan_fingerprint"]),
        asset_family=str(payload["asset_family"]),
        freqs=tuple(int(value) for value in payload["freqs"]),
        stock_codes=tuple(str(value) for value in payload["stock_codes"]),
        start_date=str(payload["start_date"]),
        end_date=str(payload["end_date"]),
        batch_partition_limit=int(payload["batch_partition_limit"]),
        target_dates_by_asset={
            str(key): tuple(str(value) for value in values)
            for key, values in dict(payload["target_dates_by_asset"]).items()
        },
        target_identities=tuple(dict(item) for item in payload["target_identities"]),
        stop_reasons=(),
        report=payload,
    )
    if _scoped_plan_fingerprint(plan) != plan.plan_fingerprint:
        raise QfqNineturnHistoryError(
            "Scoped rebuild plan fingerprint does not match its content."
        )
    return plan


def rebuild_qfq_nineturn_scope(
    *,
    plan: QfqNineturnScopedRebuildPlan,
    expected_plan_fingerprint: str,
    duckdb_resource: DuckDBResource,
    checkpoint_path: Path,
    mode: str = "batch",
    sample_partition_keys: Sequence[str] = (),
    batch_count_limit: int = 1,
    progress_callback: Callable[[Mapping[str, object]], None] | None = None,
    output_dir: Path = Path("/private/tmp"),
) -> QfqNineturnScopedRebuildReport:
    """Recompute approved codes and replace a bounded, resumable partition scope."""

    if plan.plan_fingerprint != expected_plan_fingerprint:
        raise QfqNineturnHistoryError(
            "Explicit scoped rebuild fingerprint does not match the plan."
        )
    _validate_scoped_rebuild_batch_count_limit(batch_count_limit)
    normalized_checkpoint_path = _validated_scoped_rebuild_checkpoint_path(
        checkpoint_path=checkpoint_path,
        staging_root=plan.staging_root,
    )
    checkpoint = _load_scoped_rebuild_checkpoint(
        normalized_checkpoint_path,
        plan_fingerprint=plan.plan_fingerprint,
    )
    completed = dict(checkpoint.get("completed", {}))
    all_partition_keys = _scoped_rebuild_partition_keys(plan)
    unknown_completed = tuple(sorted(set(completed) - set(all_partition_keys)))
    if unknown_completed:
        raise QfqNineturnHistoryError(
            "Scoped rebuild checkpoint contains partitions outside the plan: "
            f"{unknown_completed[:20]}."
        )
    fresh_plan = plan_qfq_nineturn_scoped_rebuild(
        lake_root=plan.lake_root,
        staging_root=plan.staging_root,
        duckdb_resource=duckdb_resource,
        asset_family=plan.asset_family,
        freqs=plan.freqs,
        stock_codes=plan.stock_codes,
        start_date=plan.start_date,
        end_date=plan.end_date,
        batch_partition_limit=plan.batch_partition_limit,
        output_dir=output_dir,
    )
    if (
        fresh_plan.history_plan_fingerprint != plan.history_plan_fingerprint
        or fresh_plan.target_dates_by_asset != plan.target_dates_by_asset
        or not _pending_scoped_rebuild_targets_match(
            plan=plan,
            fresh_plan=fresh_plan,
            completed=completed,
        )
    ):
        raise QfqNineturnHistoryError(
            "Scoped rebuild plan is stale; regenerate and review a new plan."
        )
    if fresh_plan.should_stop:
        raise QfqNineturnHistoryError(
            f"Fresh scoped rebuild plan failed: {fresh_plan.stop_reasons}."
        )
    normalized_codes = plan.stock_codes
    specs = _scoped_specs(asset_family=plan.asset_family, freqs=plan.freqs)
    selected_partition_keys = _scoped_rebuild_selection(
        plan=plan,
        completed=completed,
        mode=mode,
        sample_partition_keys=sample_partition_keys,
        batch_count_limit=batch_count_limit,
    )
    selected_bytes = _selected_scoped_rebuild_bytes(
        plan=plan,
        selected_partition_keys=selected_partition_keys,
    )
    plan.staging_root.mkdir(parents=True, exist_ok=True)
    required_free_bytes = selected_bytes * 2 + 64 * 1024 * 1024
    available_free_bytes = shutil.disk_usage(plan.staging_root).free
    if selected_partition_keys and available_free_bytes < required_free_bytes:
        raise QfqNineturnHistoryError(
            "Scoped rebuild staging space is insufficient: "
            f"required={required_free_bytes}, available={available_free_bytes}."
        )
    started = time.perf_counter()
    run_id = str(uuid.uuid4())
    run_staging_root = plan.staging_root / "qfq_nineturn_rebuild" / f"run_id={run_id}"
    backup_root = plan.staging_root / "qfq_nineturn_rebuild_backup" / f"run_id={run_id}"
    run_staging_root.mkdir(parents=True, exist_ok=False)
    backup_root.mkdir(parents=True, exist_ok=False)
    manifest_rows: list[dict[str, object]] = []
    resumed_partition_keys: list[str] = []
    replaced_partition_keys: list[str] = []
    try:
        with duckdb_resource.connect() as connection:
            for spec in specs:
                relevant_keys = tuple(
                    key
                    for key in (*completed, *selected_partition_keys)
                    if key.startswith(f"{spec.asset_key}@")
                )
                if not relevant_keys:
                    continue
                source_paths = tuple(
                    path
                    for paths in _source_paths_by_year(plan.lake_root, spec).values()
                    for path in paths
                )
                if not source_paths:
                    raise QfqNineturnHistoryError(
                        f"Scoped rebuild source is missing: {spec.asset_key}."
                    )
                full_sql = (
                    build_gold_stock_daily_qfq_nineturn_select_sql(
                        source_paths=source_paths,
                        stock_codes=normalized_codes,
                    )
                    if spec.freq is None
                    else build_gold_stk_mins_qfq_nineturn_select_sql(
                        source_paths=source_paths,
                        freq=spec.freq,
                        stock_codes=normalized_codes,
                    )
                )
                table_name = _safe_table_name(f"scope_{spec.asset_key}")
                connection.execute(
                    f"CREATE OR REPLACE TEMP TABLE {table_name} AS {full_sql}"
                )
                for partition_key, checkpoint_hash in sorted(completed.items()):
                    asset_key, trade_date = _split_scoped_rebuild_partition_key(
                        partition_key
                    )
                    if asset_key != spec.asset_key:
                        continue
                    target = _target_path(plan.lake_root, spec, trade_date)
                    _assert_scoped_rebuild_partition_ready(
                        connection=connection,
                        lake_root=plan.lake_root,
                        spec=spec,
                        target=target,
                        trade_date=trade_date,
                    )
                    if _sha256_path(target) != checkpoint_hash:
                        raise QfqNineturnHistoryError(
                            "Scoped rebuild checkpoint/target drift detected for "
                            f"{partition_key}."
                        )
                    resumed_partition_keys.append(partition_key)
                for partition_key in selected_partition_keys:
                    asset_key, trade_date = _split_scoped_rebuild_partition_key(
                        partition_key
                    )
                    if asset_key != spec.asset_key:
                        continue
                    target = _target_path(plan.lake_root, spec, trade_date)
                    staged = (
                        run_staging_root
                        / spec.asset_key
                        / f"trade_date={trade_date}"
                        / "part-000.parquet"
                    )
                    staged.parent.mkdir(parents=True, exist_ok=True)
                    code_values = ", ".join(
                        duckdb_string(code) for code in normalized_codes
                    )
                    connection.execute(
                        copy_query_to_parquet(
                            f"""
                            SELECT * FROM {read_parquet(target, hive_partitioning=False)}
                            WHERE CAST(ts_code AS VARCHAR) NOT IN ({code_values})
                            UNION ALL
                            SELECT * FROM {table_name}
                            WHERE trade_date = DATE {duckdb_string(trade_date)}
                            ORDER BY ts_code{", trade_time" if spec.freq is not None else ", trade_date"}
                            """,
                            staged,
                        )
                    )
                    _assert_partition_contract(connection, staged, spec, trade_date)
                    _assert_scoped_rebuild_partition_ready(
                        connection=connection,
                        lake_root=plan.lake_root,
                        spec=spec,
                        target=staged,
                        trade_date=trade_date,
                    )
                    backup = (
                        backup_root
                        / spec.asset_key
                        / f"trade_date={trade_date}"
                        / "part-000.parquet"
                    )
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, backup)
                    backup_sha256 = _sha256_path(backup)
                    try:
                        staged_sha256 = _sha256_path(staged)
                        os.replace(staged, target)
                        if _sha256_path(target) != staged_sha256:
                            raise QfqNineturnHistoryError(
                                f"Scoped rebuild promoted hash mismatch: {partition_key}."
                            )
                        completed[partition_key] = staged_sha256
                        _write_scoped_rebuild_checkpoint(
                            normalized_checkpoint_path,
                            plan_fingerprint=plan.plan_fingerprint,
                            completed=completed,
                        )
                    except Exception:
                        completed.pop(partition_key, None)
                        if backup.is_file():
                            os.replace(backup, target)
                        raise
                    manifest_rows.append(
                        {
                            "partition_key": partition_key,
                            "asset_key": spec.asset_key,
                            "trade_date": trade_date,
                            "target_path": str(target),
                            "target_sha256": staged_sha256,
                            "backup_path": str(backup),
                            "backup_sha256": backup_sha256,
                        }
                    )
                    replaced_partition_keys.append(partition_key)
                    if progress_callback is not None:
                        progress_callback(
                            {
                                "event": "partition_rebuilt",
                                "partition_key": partition_key,
                                "completed_partition_count": len(completed),
                                "total_partition_count": len(all_partition_keys),
                            }
                        )
    finally:
        shutil.rmtree(run_staging_root, ignore_errors=True)

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / f"qfq_nineturn_scoped_rebuild_manifest_{run_id}.json"
    _write_json(
        manifest_path,
        {
            "plan_fingerprint": plan.plan_fingerprint,
            "mode": mode,
            "selected_partition_keys": list(selected_partition_keys),
            "rows": manifest_rows,
        },
    )
    remaining_partition_count = len(all_partition_keys) - len(completed)
    return QfqNineturnScopedRebuildReport(
        asset_keys=tuple(spec.asset_key for spec in specs),
        stock_codes=normalized_codes,
        start_date=plan.start_date,
        end_date=plan.end_date,
        mode=mode,
        selected_partition_keys=selected_partition_keys,
        resumed_partition_keys=tuple(resumed_partition_keys),
        replaced_partition_count=len(replaced_partition_keys),
        remaining_partition_count=max(remaining_partition_count, 0),
        processed_batch_count=(
            (len(selected_partition_keys) + plan.batch_partition_limit - 1)
            // plan.batch_partition_limit
        ),
        checkpoint_path=normalized_checkpoint_path,
        backup_root=backup_root,
        backup_manifest_path=manifest_path,
        elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
    )


def _build_history_batch(
    connection: duckdb.DuckDBPyConnection,
    *,
    lake_root: Path,
    staging_root: Path,
    batch: QfqNineturnHistoryBatch,
    context_path: Path | None,
    seed_path: Path | None,
) -> tuple[QfqNineturnHistoryBatchResult, Path, Path]:
    started = time.perf_counter()
    spec = _spec_for_asset(batch.asset_key)
    select_sql = (
        build_gold_stock_daily_qfq_nineturn_history_batch_select_sql(
            source_paths=batch.source_paths,
            start_date=batch.start_date,
            end_date=batch.end_date,
            context_path=context_path,
            seed_path=seed_path,
        )
        if spec.freq is None
        else build_gold_stk_mins_qfq_nineturn_history_batch_select_sql(
            source_paths=batch.source_paths,
            freq=spec.freq,
            start_date=batch.start_date,
            end_date=batch.end_date,
            context_path=context_path,
            seed_path=seed_path,
        )
    )
    table_name = _safe_table_name(f"history_{batch.asset_key}_{batch.year}")
    connection.execute(f"CREATE OR REPLACE TEMP TABLE {table_name} AS {select_sql}")
    output_row_count = int(
        connection.execute(f"SELECT count(*) FROM {table_name}").fetchone()[0]
    )
    if output_row_count != batch.source_row_count:
        raise QfqNineturnHistoryError(
            f"History row count mismatch for {batch.asset_key}:{batch.year}: "
            f"source={batch.source_row_count}, output={output_row_count}."
        )
    _assert_batch_key_equality(
        connection, table_name=table_name, batch=batch, spec=spec
    )

    batch_root = staging_root / batch.asset_key / f"year={batch.year}"
    partitioned_root = batch_root / "partitioned"
    partitioned_root.mkdir(parents=True, exist_ok=False)
    connection.execute(
        f"""
        COPY (
          SELECT *, strftime(trade_date, '%Y-%m-%d') AS partition_trade_date
          FROM {table_name}
        ) TO {duckdb_string(partitioned_root)} (
          FORMAT PARQUET,
          COMPRESSION ZSTD,
          PARTITION_BY (partition_trade_date)
        )
        """
    )
    staged_by_date = _normalize_partitioned_batch(
        connection=connection,
        partitioned_root=partitioned_root,
        normalized_root=batch_root / "normalized",
        expected_dates=batch.trade_dates,
        spec=spec,
    )
    for trade_date, staged in staged_by_date.items():
        _assert_partition_contract(connection, staged, spec, trade_date)

    state_root = staging_root / batch.asset_key / "state"
    next_context, next_seed, context_row_count, seed_row_count = (
        _write_compact_history_state(
            connection,
            table_name=table_name,
            source_paths=batch.source_paths,
            context_path=context_path,
            seed_path=seed_path,
            spec=spec,
            state_root=state_root,
            year=batch.year,
        )
    )

    promoted: list[Path] = []
    reused = 0
    try:
        for trade_date in batch.trade_dates:
            staged = staged_by_date[trade_date]
            target = _target_path(lake_root, spec, trade_date)
            if target.is_file():
                if not _parquet_rows_equal(connection, target, staged):
                    raise QfqNineturnHistoryError(
                        f"Existing history target conflicts with staged output: {target}."
                    )
                reused += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, target)
            promoted.append(target)
    except Exception:
        for target in reversed(promoted):
            target.unlink(missing_ok=True)
        raise
    return (
        QfqNineturnHistoryBatchResult(
            asset_key=batch.asset_key,
            freq=batch.freq,
            year=batch.year,
            source_row_count=batch.source_row_count,
            output_row_count=output_row_count,
            target_file_count=len(batch.trade_dates),
            promoted_file_count=len(promoted),
            reused_file_count=reused,
            context_row_count=context_row_count,
            seed_row_count=seed_row_count,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        ),
        next_context,
        next_seed,
    )


def _profile_batch(
    connection: duckdb.DuckDBPyConnection,
    *,
    lake_root: Path,
    spec: _AssetSpec,
    year: int,
    source_paths: tuple[Path, ...],
) -> QfqNineturnHistoryBatch:
    source_sql = _source_rows_sql(source_paths, spec)
    null_predicate = (
        "ts_code IS NULL OR trade_date IS NULL OR trade_time IS NULL OR close_qfq IS NULL"
        if spec.freq is not None
        else "ts_code IS NULL OR trade_date IS NULL OR close_qfq IS NULL"
    )
    wrong_freq_predicate = f"freq != {spec.freq}" if spec.freq is not None else "false"
    key_columns = (
        "ts_code, trade_date" if spec.freq is None else "ts_code, freq, trade_time"
    )
    row = connection.execute(
        f"""
        SELECT
          count(*) AS row_count,
          count(DISTINCT ts_code) AS stock_code_count,
          count(*) FILTER (WHERE {null_predicate}) AS null_key_count,
          count(*) FILTER (WHERE year(trade_date) != {year}) AS wrong_year_count,
          count(*) FILTER (WHERE {wrong_freq_predicate}) AS wrong_freq_count,
          count(*) - count(DISTINCT ({key_columns})) AS duplicate_key_count,
          list(
            DISTINCT strftime(trade_date, '%Y-%m-%d')
            ORDER BY strftime(trade_date, '%Y-%m-%d')
          ) AS trade_dates
        FROM ({source_sql})
        """
    ).fetchone()
    trade_dates = tuple(str(value) for value in (row[6] or ()))
    existing_target_count = sum(
        _target_path(lake_root, spec, trade_date).is_file()
        for trade_date in trade_dates
    )
    return QfqNineturnHistoryBatch(
        asset_key=spec.asset_key,
        freq=spec.freq,
        year=year,
        source_paths=source_paths,
        source_file_count=len(source_paths),
        source_row_count=int(row[0]),
        source_bytes=sum(path.stat().st_size for path in source_paths),
        source_fingerprint=_source_fingerprint(lake_root, source_paths),
        trade_dates=trade_dates,
        stock_code_count=int(row[1]),
        null_key_count=int(row[2]),
        duplicate_key_count=int(row[5]),
        wrong_year_count=int(row[3]),
        wrong_freq_count=int(row[4]),
        existing_target_file_count=existing_target_count,
    )


def _asset_specs() -> tuple[_AssetSpec, ...]:
    return (
        _AssetSpec(
            asset_key="gold_stock_daily_qfq_nineturn",
            freq=None,
            schema=tuple(GOLD_STOCK_DAILY_QFQ_NINETURN_SCHEMA),
        ),
        *(
            _AssetSpec(
                asset_key=f"gold_stk_mins_qfq_nineturn_{freq}m",
                freq=freq,
                schema=tuple(GOLD_STK_MINS_QFQ_NINETURN_SCHEMA),
            )
            for freq in QFQ_NINETURN_MINUTE_FREQS
        ),
    )


def _selected_asset_specs(asset_keys: Sequence[str] | None) -> tuple[_AssetSpec, ...]:
    specs = _asset_specs()
    if asset_keys is None:
        return specs
    normalized = tuple(dict.fromkeys(str(value) for value in asset_keys))
    known = {spec.asset_key for spec in specs}
    unknown = tuple(value for value in normalized if value not in known)
    if unknown:
        raise QfqNineturnHistoryError(f"Unsupported QFQ nine-turn assets: {unknown}.")
    if not normalized:
        raise QfqNineturnHistoryError("History plan requires at least one asset.")
    selected = set(normalized)
    return tuple(spec for spec in specs if spec.asset_key in selected)


def _spec_for_asset(asset_key: str) -> _AssetSpec:
    for spec in _asset_specs():
        if spec.asset_key == asset_key:
            return spec
    raise QfqNineturnHistoryError(f"Unsupported QFQ nine-turn asset: {asset_key}.")


def _scoped_specs(*, asset_family: str, freqs: Sequence[int]) -> tuple[_AssetSpec, ...]:
    if asset_family == "daily":
        if freqs:
            raise QfqNineturnHistoryError("Daily scoped rebuild does not accept freqs.")
        return (_asset_specs()[0],)
    if asset_family != "minute":
        raise QfqNineturnHistoryError("asset_family must be daily or minute.")
    normalized = tuple(sorted({int(freq) for freq in freqs}))
    if not normalized or any(
        freq not in QFQ_NINETURN_MINUTE_FREQS for freq in normalized
    ):
        raise QfqNineturnHistoryError(
            "Minute scoped rebuild requires supported explicit frequencies."
        )
    return tuple(spec for spec in _asset_specs() if spec.freq in normalized)


def _source_paths_by_year(
    lake_root: Path, spec: _AssetSpec
) -> dict[int, tuple[Path, ...]]:
    grouped: dict[int, list[Path]] = {}
    if spec.freq is None:
        root = lake_root / "gold" / "quote" / "stock_daily_qfq"
        for path in sorted(root.glob("trade_date=*/part-000.parquet")):
            trade_date = path.parent.name.removeprefix("trade_date=")
            try:
                year = date.fromisoformat(trade_date).year
            except ValueError:
                continue
            grouped.setdefault(year, []).append(path)
    else:
        root = lake_root / "gold" / "quote" / "stk_mins_qfq" / f"freq={spec.freq}"
        for path in sorted(root.glob("ts_code=*/year=*/part-000.parquet")):
            try:
                year = int(path.parent.name.removeprefix("year="))
            except ValueError:
                continue
            grouped.setdefault(year, []).append(path)
    return {year: tuple(paths) for year, paths in grouped.items()}


def _source_rows_sql(source_paths: Sequence[Path], spec: _AssetSpec) -> str:
    source = _read_paths(source_paths)
    if spec.freq is None:
        return f"""
        SELECT
          CAST(ts_code AS VARCHAR) AS ts_code,
          NULL::INTEGER AS freq,
          CAST(trade_date AS DATE) AS trade_date,
          NULL::TIMESTAMP AS trade_time,
          CAST(trade_date AS TIMESTAMP) AS bar_time,
          CAST(close AS DOUBLE) AS close_qfq
        FROM {source}
        """
    return f"""
    SELECT
      CAST(ts_code AS VARCHAR) AS ts_code,
      CAST(freq AS INTEGER) AS freq,
      CAST(trade_date AS DATE) AS trade_date,
      CAST(trade_time AS TIMESTAMP) AS trade_time,
      CAST(trade_time AS TIMESTAMP) AS bar_time,
      CAST(close AS DOUBLE) AS close_qfq
    FROM {source}
    WHERE CAST(freq AS INTEGER) = {spec.freq}
    """


def _history_context_rows_sql(
    *,
    source_paths: Sequence[Path],
    context_path: Path | None,
    freq: int | None,
) -> str:
    spec = _spec_for_asset(
        "gold_stock_daily_qfq_nineturn"
        if freq is None
        else f"gold_stk_mins_qfq_nineturn_{freq}m"
    )
    current = _source_rows_sql(source_paths, spec)
    if context_path is None:
        return current
    return f"""
    SELECT * FROM {read_parquet(context_path, hive_partitioning=False)}
    UNION ALL
    SELECT * FROM ({current})
    """


def _write_compact_history_state(
    connection: duckdb.DuckDBPyConnection,
    *,
    table_name: str,
    source_paths: Sequence[Path],
    context_path: Path | None,
    seed_path: Path | None,
    spec: _AssetSpec,
    state_root: Path,
    year: int,
) -> tuple[Path, Path, int, int]:
    state_root.mkdir(parents=True, exist_ok=True)
    next_context = state_root / f"context_{year}.parquet"
    next_seed = state_root / f"seed_{year}.parquet"
    context_rows_sql = _history_context_rows_sql(
        source_paths=source_paths,
        context_path=context_path,
        freq=spec.freq,
    )
    connection.execute(
        copy_query_to_parquet(
            f"""
            SELECT ts_code, freq, trade_date, trade_time, bar_time, close_qfq
            FROM ({context_rows_sql})
            QUALIFY ROW_NUMBER() OVER (
              PARTITION BY ts_code ORDER BY bar_time DESC
            ) <= {QFQ_NINETURN_COMPARISON_LAG}
            ORDER BY ts_code, bar_time
            """,
            next_context,
        )
    )
    order_column = "trade_date" if spec.freq is None else "trade_time"
    current_seed_sql = f"""
    SELECT
      CAST(ts_code AS VARCHAR) AS ts_code,
      CASE WHEN up_count > 0 THEN 1 WHEN down_count > 0 THEN -1 ELSE 0 END
        AS seed_direction,
      greatest(CAST(up_count AS INTEGER), CAST(down_count AS INTEGER)) AS seed_count
    FROM {table_name}
    QUALIFY ROW_NUMBER() OVER (
      PARTITION BY ts_code ORDER BY {order_column} DESC
    ) = 1
    """
    seed_rows_sql = current_seed_sql
    if seed_path is not None:
        seed_rows_sql = f"""
        WITH current_seed AS (
          {current_seed_sql}
        ),
        previous_seed AS (
          SELECT
            CAST(ts_code AS VARCHAR) AS ts_code,
            CAST(seed_direction AS INTEGER) AS seed_direction,
            CAST(seed_count AS INTEGER) AS seed_count
          FROM {read_parquet(seed_path, hive_partitioning=False)}
        )
        SELECT * FROM current_seed
        UNION ALL
        SELECT previous_seed.*
        FROM previous_seed
        LEFT JOIN current_seed USING (ts_code)
        WHERE current_seed.ts_code IS NULL
        """
    connection.execute(
        copy_query_to_parquet(
            f"SELECT * FROM ({seed_rows_sql}) ORDER BY ts_code",
            next_seed,
        )
    )
    context_relation = read_parquet(next_context, hive_partitioning=False)
    seed_relation = read_parquet(next_seed, hive_partitioning=False)
    state_row = connection.execute(
        f"""
        SELECT
          (SELECT count(*) FROM {context_relation}) AS context_row_count,
          (SELECT count(*) FROM {seed_relation}) AS seed_row_count,
          (
            SELECT coalesce(sum(row_count - 1), 0)
            FROM (
              SELECT ts_code, count(*) AS row_count
              FROM {seed_relation}
              GROUP BY ts_code
              HAVING count(*) > 1
            )
          ) AS duplicate_seed_count,
          (
            SELECT coalesce(max(row_count), 0)
            FROM (
              SELECT ts_code, count(*) AS row_count
              FROM {context_relation}
              GROUP BY ts_code
            )
          ) AS max_context_rows_per_code,
          (
            SELECT count(*) FROM (
              (SELECT DISTINCT ts_code FROM {context_relation}
               EXCEPT
               SELECT ts_code FROM {seed_relation})
              UNION ALL
              (SELECT ts_code FROM {seed_relation}
               EXCEPT
               SELECT DISTINCT ts_code FROM {context_relation})
            )
          ) AS code_set_difference_count
        """
    ).fetchone()
    context_row_count = int(state_row[0])
    seed_row_count = int(state_row[1])
    duplicate_seed_count = int(state_row[2])
    max_context_rows_per_code = int(state_row[3])
    code_set_difference_count = int(state_row[4])
    if (
        duplicate_seed_count
        or max_context_rows_per_code > QFQ_NINETURN_COMPARISON_LAG
        or code_set_difference_count
        or context_row_count > seed_row_count * QFQ_NINETURN_COMPARISON_LAG
    ):
        raise QfqNineturnHistoryError(
            "Compact history state contract failed: "
            f"context_rows={context_row_count}, seed_rows={seed_row_count}, "
            f"duplicate_seed={duplicate_seed_count}, "
            f"max_context_rows_per_code={max_context_rows_per_code}, "
            f"code_set_difference={code_set_difference_count}."
        )
    return next_context, next_seed, context_row_count, seed_row_count


def _target_path(lake_root: Path, spec: _AssetSpec, trade_date: str) -> Path:
    if spec.freq is None:
        return gold_stock_daily_qfq_nineturn_path(lake_root, trade_date)
    return gold_stk_mins_qfq_nineturn_path(lake_root, spec.freq, trade_date)


def _assert_batch_key_equality(
    connection: duckdb.DuckDBPyConnection,
    *,
    table_name: str,
    batch: QfqNineturnHistoryBatch,
    spec: _AssetSpec,
) -> None:
    source = _source_rows_sql(batch.source_paths, spec)
    key_columns = (
        "ts_code, trade_date" if spec.freq is None else "ts_code, freq, trade_time"
    )
    differences = int(
        connection.execute(
            f"""
            SELECT count(*) FROM (
              (SELECT {key_columns} FROM ({source})
               EXCEPT ALL
               SELECT {key_columns} FROM {table_name})
              UNION ALL
              (SELECT {key_columns} FROM {table_name}
               EXCEPT ALL
               SELECT {key_columns} FROM ({source}))
            )
            """
        ).fetchone()[0]
    )
    if differences:
        raise QfqNineturnHistoryError(
            f"Source/output key difference for {batch.asset_key}:{batch.year}: {differences}."
        )


def _normalize_partitioned_batch(
    *,
    connection: duckdb.DuckDBPyConnection,
    partitioned_root: Path,
    normalized_root: Path,
    expected_dates: Sequence[str],
    spec: _AssetSpec,
) -> dict[str, Path]:
    normalized: dict[str, Path] = {}
    expected_date_set = set(expected_dates)
    output_columns = ", ".join(column.name for column in spec.schema)
    order_columns = (
        "ts_code, trade_date" if spec.freq is None else "ts_code, freq, trade_time"
    )
    for trade_date in expected_dates:
        source_dir = partitioned_root / f"partition_trade_date={trade_date}"
        parquet_files = tuple(sorted(source_dir.glob("*.parquet"), key=str))
        if not parquet_files:
            raise QfqNineturnHistoryError(
                f"Expected staged parquet rows for {trade_date}; got 0 files."
            )
        target = normalized_root / f"trade_date={trade_date}" / "part-000.parquet"
        target.parent.mkdir(parents=True, exist_ok=True)
        connection.execute(
            f"""
            COPY (
              SELECT {output_columns}
              FROM {_read_paths(parquet_files)}
              ORDER BY {order_columns}
            ) TO {duckdb_string(target)} (
              FORMAT PARQUET,
              COMPRESSION ZSTD
            )
            """
        )
        normalized[trade_date] = target
    unexpected = tuple(
        path
        for path in partitioned_root.glob("partition_trade_date=*/*.parquet")
        if path.parent.name.removeprefix("partition_trade_date=")
        not in expected_date_set
    )
    if unexpected:
        raise QfqNineturnHistoryError(
            f"Unexpected staged partitions: {[str(path) for path in unexpected[:MAX_REPORT_SAMPLES]]}."
        )
    return normalized


def _assert_partition_contract(
    connection: duckdb.DuckDBPyConnection,
    path: Path,
    spec: _AssetSpec,
    trade_date: str,
) -> None:
    if not _schema_matches(connection, path, spec.schema):
        raise QfqNineturnHistoryError(f"Staged schema mismatch: {path}.")
    duplicate_count, null_count, wrong_date_count, wrong_freq_count = (
        _target_contract_counts(connection, (path,), spec, expected_date=trade_date)
    )
    row_count = _count_rows(connection, (path,))
    if (
        row_count <= 0
        or duplicate_count
        or null_count
        or wrong_date_count
        or wrong_freq_count
    ):
        raise QfqNineturnHistoryError(
            "Staged partition contract failed: "
            f"path={path}, rows={row_count}, duplicate={duplicate_count}, "
            f"null={null_count}, date={wrong_date_count}, freq={wrong_freq_count}."
        )


def _assert_scoped_rebuild_partition_ready(
    *,
    connection: duckdb.DuckDBPyConnection,
    lake_root: Path,
    spec: _AssetSpec,
    target: Path,
    trade_date: str,
) -> None:
    source_paths = (
        (gold_stock_daily_qfq_path(lake_root, trade_date),)
        if spec.freq is None
        else _source_paths_by_year(lake_root, spec).get(
            date.fromisoformat(trade_date).year,
            (),
        )
    )
    diagnostics = audit_qfq_nineturn_integrity(
        connection,
        target_path=target,
        source_paths=source_paths,
        partition_key=trade_date,
        freq=spec.freq,
    )
    if not diagnostics.passed:
        raise QfqNineturnHistoryError(
            "Scoped rebuild partition readiness failed: "
            f"asset={spec.asset_key}, trade_date={trade_date}, "
            f"rules={diagnostics.failed_rule_names}."
        )


def _target_contract_counts(
    connection: duckdb.DuckDBPyConnection,
    paths: Sequence[Path],
    spec: _AssetSpec,
    *,
    expected_date: str | None = None,
) -> tuple[int, int, int, int]:
    if not paths:
        return 0, 0, 0, 0
    source = _read_paths(paths)
    key_columns = (
        "ts_code, trade_date" if spec.freq is None else "ts_code, freq, trade_time"
    )
    duplicate_count = int(
        connection.execute(
            f"""
            SELECT coalesce(sum(row_count - 1), 0)
            FROM (
              SELECT {key_columns}, count(*) AS row_count
              FROM {source}
              GROUP BY {key_columns}
              HAVING count(*) > 1
            )
            """
        ).fetchone()[0]
    )
    date_predicate = (
        f"CAST(trade_date AS DATE) != DATE {duckdb_string(expected_date)}"
        if expected_date is not None
        else "false"
    )
    null_predicate = (
        "ts_code IS NULL OR trade_date IS NULL OR trade_time IS NULL OR close_qfq IS NULL"
        if spec.freq is not None
        else "ts_code IS NULL OR trade_date IS NULL OR close_qfq IS NULL"
    )
    wrong_freq_predicate = (
        f"CAST(freq AS INTEGER) != {spec.freq}" if spec.freq is not None else "false"
    )
    row = connection.execute(
        f"""
        SELECT
          count(*) FILTER (WHERE {null_predicate}),
          count(*) FILTER (WHERE {date_predicate}),
          count(*) FILTER (WHERE {wrong_freq_predicate})
        FROM {source}
        """
    ).fetchone()
    return duplicate_count, int(row[0]), int(row[1]), int(row[2])


def _schema_matches(
    connection: duckdb.DuckDBPyConnection,
    path: Path,
    schema: Sequence[ColumnContract],
) -> bool:
    observed = tuple(
        (str(name), str(data_type).upper())
        for name, data_type, *_rest in connection.execute(
            describe_parquet_query(path, hive_partitioning=False)
        ).fetchall()
    )
    expected = tuple((column.name, column.type.upper()) for column in schema)
    return observed == expected


def _parquet_rows_equal(
    connection: duckdb.DuckDBPyConnection,
    left: Path,
    right: Path,
) -> bool:
    difference = int(
        connection.execute(
            f"""
            SELECT count(*) FROM (
              (SELECT * FROM {read_parquet(left, hive_partitioning=False)}
               EXCEPT ALL
               SELECT * FROM {read_parquet(right, hive_partitioning=False)})
              UNION ALL
              (SELECT * FROM {read_parquet(right, hive_partitioning=False)}
               EXCEPT ALL
               SELECT * FROM {read_parquet(left, hive_partitioning=False)})
            )
            """
        ).fetchone()[0]
    )
    return difference == 0


def _read_paths(paths: Sequence[Path]) -> str:
    normalized = tuple(Path(path) for path in paths)
    if not normalized:
        raise QfqNineturnHistoryError("At least one parquet path is required.")
    if len(normalized) == 1:
        return read_parquet(normalized[0], hive_partitioning=False)
    values = ", ".join(duckdb_string(path) for path in normalized)
    return f"read_parquet([{values}], hive_partitioning=false, union_by_name=true)"


def _source_fingerprint(lake_root: Path, paths: Sequence[Path]) -> str:
    root = lake_root.resolve()
    digest = hashlib.sha256()
    for path in sorted((Path(path) for path in paths), key=str):
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(root).as_posix()
        except ValueError as exc:
            raise QfqNineturnHistoryError(
                f"Source file is outside Lake root: {path}."
            ) from exc
        stat = resolved.stat()
        digest.update(f"{relative}\t{stat.st_size}\t{stat.st_mtime_ns}\n".encode())
    return digest.hexdigest()


def _plan_payload(
    *,
    lake_root: Path,
    batches: Sequence[QfqNineturnHistoryBatch],
    latest_dates: Mapping[str, Sequence[str]],
    stop_reasons: Sequence[str],
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "build_method": BUILD_METHOD,
        "lake_root": str(lake_root.resolve()),
        "batches": [batch.to_dict() for batch in batches],
        "latest_check_dates_by_asset": {
            key: list(value) for key, value in sorted(latest_dates.items())
        },
        "stop_reasons": sorted(set(stop_reasons)),
    }


def _plan_fingerprint(plan: QfqNineturnHistoryPlan) -> str:
    return _hash_payload(
        _plan_payload(
            lake_root=plan.lake_root,
            batches=plan.batches,
            latest_dates=plan.latest_check_dates_by_asset,
            stop_reasons=plan.stop_reasons,
        )
    )


def _scoped_plan_fingerprint(plan: QfqNineturnScopedRebuildPlan) -> str:
    return _hash_payload(
        {
            "schema_version": SCHEMA_VERSION,
            "phase": SCOPED_PLAN_PHASE,
            "history_plan_fingerprint": plan.history_plan_fingerprint,
            "staging_root": str(plan.staging_root.resolve()),
            "asset_family": plan.asset_family,
            "freqs": list(plan.freqs),
            "stock_codes": list(plan.stock_codes),
            "start_date": plan.start_date,
            "end_date": plan.end_date,
            "batch_partition_limit": plan.batch_partition_limit,
            "target_dates_by_asset": {
                key: list(value)
                for key, value in sorted(plan.target_dates_by_asset.items())
            },
            "target_identities": [dict(item) for item in plan.target_identities],
            "stop_reasons": list(plan.stop_reasons),
        }
    )


def _batch_from_payload(
    payload: Mapping[str, object],
    *,
    lake_root: Path,
) -> QfqNineturnHistoryBatch:
    spec = _spec_for_asset(str(payload["asset_key"]))
    year = int(payload["year"])
    source_paths = _source_paths_by_year(lake_root, spec).get(year, ())
    return QfqNineturnHistoryBatch(
        asset_key=spec.asset_key,
        freq=spec.freq,
        year=year,
        source_paths=source_paths,
        source_file_count=int(payload["source_file_count"]),
        source_row_count=int(payload["source_row_count"]),
        source_bytes=int(payload["source_bytes"]),
        source_fingerprint=str(payload["source_fingerprint"]),
        trade_dates=tuple(str(value) for value in payload["trade_dates"]),
        stock_code_count=int(payload["stock_code_count"]),
        null_key_count=int(payload["null_key_count"]),
        duplicate_key_count=int(payload["duplicate_key_count"]),
        wrong_year_count=int(payload["wrong_year_count"]),
        wrong_freq_count=int(payload["wrong_freq_count"]),
        existing_target_file_count=int(payload["existing_target_file_count"]),
    )


def _batch_sort_key(batch: QfqNineturnHistoryBatch) -> tuple[int, int]:
    asset_order = {spec.asset_key: index for index, spec in enumerate(_asset_specs())}
    return asset_order[batch.asset_key], batch.year


def _safe_table_name(value: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in value)


def _normalize_stock_codes(stock_codes: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        sorted({str(code).strip().upper() for code in stock_codes if str(code).strip()})
    )


def _hash_payload(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _count_rows(
    connection: duckdb.DuckDBPyConnection,
    paths: Sequence[Path],
) -> int:
    if not paths:
        return 0
    return int(
        connection.execute(f"SELECT count(*) FROM {_read_paths(paths)}").fetchone()[0]
    )


def _validate_date_range(start_date: str, end_date: str) -> None:
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError as exc:
        raise QfqNineturnHistoryError("Dates must use YYYY-MM-DD format.") from exc
    if start > end:
        raise QfqNineturnHistoryError("start_date must not be after end_date.")


def _validate_scoped_rebuild_batch_partition_limit(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise QfqNineturnHistoryError(
            "Scoped rebuild batch partition limit must be an integer."
        )
    if value <= 0 or value > MAX_SCOPED_REBUILD_BATCH_PARTITION_COUNT:
        raise QfqNineturnHistoryError(
            "Scoped rebuild batch partition limit must be between 1 and "
            f"{MAX_SCOPED_REBUILD_BATCH_PARTITION_COUNT}."
        )


def _validate_scoped_rebuild_batch_count_limit(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise QfqNineturnHistoryError(
            "Scoped rebuild batch count limit must be an integer."
        )
    if value <= 0 or value > MAX_SCOPED_REBUILD_BATCH_COUNT_PER_RUN:
        raise QfqNineturnHistoryError(
            "Scoped rebuild batch count limit must be between 1 and "
            f"{MAX_SCOPED_REBUILD_BATCH_COUNT_PER_RUN}."
        )


def _scoped_rebuild_partition_key(asset_key: str, trade_date: str) -> str:
    return f"{asset_key}@{trade_date}"


def _split_scoped_rebuild_partition_key(value: str) -> tuple[str, str]:
    asset_key, separator, trade_date = str(value).partition("@")
    if not separator or not asset_key:
        raise QfqNineturnHistoryError(f"Invalid scoped rebuild partition key: {value}.")
    _validate_date_range(trade_date, trade_date)
    return asset_key, trade_date


def _scoped_rebuild_partition_keys(
    plan: QfqNineturnScopedRebuildPlan,
) -> tuple[str, ...]:
    return tuple(
        _scoped_rebuild_partition_key(asset_key, trade_date)
        for asset_key, trade_dates in sorted(plan.target_dates_by_asset.items())
        for trade_date in trade_dates
    )


def _scoped_rebuild_selection(
    *,
    plan: QfqNineturnScopedRebuildPlan,
    completed: Mapping[str, object],
    mode: str,
    sample_partition_keys: Sequence[str],
    batch_count_limit: int,
) -> tuple[str, ...]:
    all_keys = _scoped_rebuild_partition_keys(plan)
    pending = tuple(value for value in all_keys if value not in completed)
    if mode == "batch":
        if sample_partition_keys:
            raise QfqNineturnHistoryError(
                "Scoped rebuild batch mode does not accept sample partitions."
            )
        return pending[: plan.batch_partition_limit * batch_count_limit]
    if mode != "sample":
        raise QfqNineturnHistoryError("Scoped rebuild mode must be sample or batch.")
    samples = tuple(dict.fromkeys(str(value) for value in sample_partition_keys))
    if not samples or len(samples) > MAX_SCOPED_REBUILD_SAMPLE_PARTITION_COUNT:
        raise QfqNineturnHistoryError(
            "Scoped rebuild sample mode requires one to three explicit partitions."
        )
    invalid = tuple(value for value in samples if value not in set(all_keys))
    if invalid:
        raise QfqNineturnHistoryError(
            f"Scoped rebuild sample partitions are outside the plan: {invalid}."
        )
    return tuple(value for value in samples if value not in completed)


def _selected_scoped_rebuild_bytes(
    *,
    plan: QfqNineturnScopedRebuildPlan,
    selected_partition_keys: Sequence[str],
) -> int:
    selected = set(selected_partition_keys)
    return sum(
        int(identity["size"])
        for identity in plan.target_identities
        if _scoped_rebuild_partition_key(
            str(identity["asset_key"]),
            str(identity["partition_key"]),
        )
        in selected
    )


def _pending_scoped_rebuild_targets_match(
    *,
    plan: QfqNineturnScopedRebuildPlan,
    fresh_plan: QfqNineturnScopedRebuildPlan,
    completed: Mapping[str, object],
) -> bool:
    def pending_identities(
        candidate: QfqNineturnScopedRebuildPlan,
    ) -> dict[str, Mapping[str, object]]:
        return {
            _scoped_rebuild_partition_key(
                str(identity["asset_key"]),
                str(identity["partition_key"]),
            ): identity
            for identity in candidate.target_identities
            if _scoped_rebuild_partition_key(
                str(identity["asset_key"]),
                str(identity["partition_key"]),
            )
            not in completed
        }

    return pending_identities(plan) == pending_identities(fresh_plan)


def _validated_scoped_rebuild_checkpoint_path(
    *,
    checkpoint_path: Path,
    staging_root: Path,
) -> Path:
    normalized = Path(checkpoint_path).resolve()
    try:
        normalized.relative_to(staging_root.resolve())
    except ValueError as error:
        raise QfqNineturnHistoryError(
            "Scoped rebuild checkpoint must be below the reviewed staging root."
        ) from error
    return normalized


def _load_scoped_rebuild_checkpoint(
    path: Path,
    *,
    plan_fingerprint: str,
) -> dict[str, object]:
    if not path.exists():
        return {"completed": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("phase") != SCOPED_REBUILD_CHECKPOINT_PHASE
        or payload.get("plan_fingerprint") != plan_fingerprint
    ):
        raise QfqNineturnHistoryError(
            "Scoped rebuild checkpoint does not belong to the reviewed plan."
        )
    completed = payload.get("completed")
    if not isinstance(completed, dict):
        raise QfqNineturnHistoryError("Scoped rebuild checkpoint is malformed.")
    return {"completed": {str(key): str(value) for key, value in completed.items()}}


def _write_scoped_rebuild_checkpoint(
    path: Path,
    *,
    plan_fingerprint: str,
    completed: Mapping[str, object],
) -> None:
    _write_json_atomic(
        path,
        {
            "schema_version": SCHEMA_VERSION,
            "phase": SCOPED_REBUILD_CHECKPOINT_PHASE,
            "plan_fingerprint": plan_fingerprint,
            "completed": dict(sorted(completed.items())),
            "completed_partition_count": len(completed),
            "updated_at": datetime.now(UTC).isoformat(),
        },
    )


def _validated_staging_root(*, lake_root: Path, staging_root: Path) -> Path:
    normalized_lake_root = Path(lake_root).resolve()
    normalized_staging_root = Path(staging_root).resolve()
    if normalized_staging_root == normalized_lake_root:
        raise QfqNineturnHistoryError("Staging root must be separate from Lake root.")
    formal_lake_root = Path(DEFAULT_LAKE_ROOT).resolve()
    formal_staging_root = Path(DEFAULT_LAKE_STAGING_ROOT).resolve()
    if normalized_lake_root != formal_lake_root:
        return normalized_staging_root
    if normalized_staging_root != formal_staging_root:
        raise QfqNineturnHistoryError(
            "Formal Lake writes must use the fixed data_lake_staging root."
        )
    try:
        normalized_staging_root.relative_to(normalized_lake_root)
    except ValueError:
        return normalized_staging_root
    raise QfqNineturnHistoryError(
        "Staging root must not be located inside the formal Lake root."
    )


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
