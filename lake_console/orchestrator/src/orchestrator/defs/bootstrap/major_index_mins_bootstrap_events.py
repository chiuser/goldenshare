"""Runless Dagster event backfill for verified major-index minute files."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
import hashlib
import json
import logging
from pathlib import Path
from time import perf_counter
from typing import Any

import dagster as dg
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs.bootstrap.major_index_mins_bootstrap_plan import (
    MajorIndexMinsDatePlan,
    build_date_plan,
)
from orchestrator.defs.partitions import cn_major_index_mins_trade_days
from orchestrator.defs.paths import (
    raw_major_index_mins_path,
    silver_major_index_mins_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_MAJOR_INDEX_MINS_SCHEMA,
    SILVER_MAJOR_INDEX_MINS_SCHEMA,
)
from orchestrator.defs.run_contracts.major_index_mins import (
    MAJOR_INDEX_MINS_RAW_ASSET_KEYS,
    MAJOR_INDEX_MINS_RAW_CHECKS,
    MAJOR_INDEX_MINS_SILVER_ASSET_KEYS,
    MAJOR_INDEX_MINS_SILVER_CHECKS,
    MAJOR_INDEX_MINS_SILVER_FREQS,
    MAJOR_INDEX_MINS_SOURCE_FREQS,
)
from orchestrator.defs.run_contracts.metadata import (
    CheckScope,
    build_check_metadata,
    build_materialization_metadata,
)


LOGGER = logging.getLogger(__name__)

MAJOR_INDEX_MINS_EVENT_WINDOW_SIZE = 20
MAJOR_INDEX_MINS_PARTITION_SET = cn_major_index_mins_trade_days.name
MAJOR_INDEX_MINS_EVENT_PROGRESS_INTERVAL = 1_000
_CHECK_HISTORY_LIMIT = 100
_SAMPLE_LIMIT = 10
_ACTIVE_RUN_STATUSES = (
    dg.DagsterRunStatus.QUEUED,
    dg.DagsterRunStatus.STARTING,
    dg.DagsterRunStatus.STARTED,
    dg.DagsterRunStatus.CANCELING,
)


class MajorIndexMinsEventPlanError(ValueError):
    """Raised when P8 cannot trust the frozen P7 file facts."""


@dataclass(frozen=True, slots=True)
class MajorIndexMinsEventAssetSpec:
    layer: str
    frequency: str
    asset_key: dg.AssetKey
    check_name: str
    path_builder: Callable[[Path, str | int, str], Path]
    observed_columns: tuple[str, ...]
    source_method: str


@dataclass(frozen=True, slots=True)
class MajorIndexMinsEventFile:
    asset_key: str
    partition_key: str
    file_path: Path
    row_count: int
    layer: str
    frequency: str
    source_empty_exempt: bool = False


@dataclass(frozen=True, slots=True)
class MajorIndexMinsEventAssetPlan:
    spec: MajorIndexMinsEventAssetSpec
    files: tuple[MajorIndexMinsEventFile, ...]
    recent_check_dates: tuple[str, ...]
    existing_materialized_dates: tuple[str, ...]
    existing_ready_check_dates: tuple[str, ...]

    @property
    def planned_materialization_count(self) -> int:
        existing = set(self.existing_materialized_dates)
        return sum(value.partition_key not in existing for value in self.files)

    @property
    def planned_check_count(self) -> int:
        existing = set(self.existing_ready_check_dates)
        return sum(value not in existing for value in self.recent_check_dates)


@dataclass(frozen=True, slots=True)
class MajorIndexMinsEventPlan:
    lake_root: Path
    date_plan_report_path: Path
    promote_report_path: Path
    fallback_report_path: Path
    date_plan: MajorIndexMinsDatePlan
    recent_check_dates: tuple[str, ...]
    selected_asset_keys: tuple[str, ...]
    asset_plans: tuple[MajorIndexMinsEventAssetPlan, ...]
    registered_partition_count: int
    missing_registered_dates: tuple[str, ...]
    active_run_count: int
    p7e_report_sha256: str
    fallback_report_sha256: str
    source_empty_raw_keys: tuple[str, ...]
    inventory_file_count: int
    inventory_row_count: int
    inventory_elapsed_ms: float
    precondition_errors: tuple[str, ...]

    @property
    def should_stop(self) -> bool:
        return bool(self.precondition_errors) or bool(self.missing_registered_dates)

    @property
    def planned_materialization_count(self) -> int:
        return sum(value.planned_materialization_count for value in self.asset_plans)

    @property
    def planned_check_count(self) -> int:
        return sum(value.planned_check_count for value in self.asset_plans)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "lake_root": str(self.lake_root),
            "partition_set": MAJOR_INDEX_MINS_PARTITION_SET,
            "date_plan_report_path": str(self.date_plan_report_path),
            "promote_report_path": str(self.promote_report_path),
            "fallback_report_path": str(self.fallback_report_path),
            "p7e_report_sha256": self.p7e_report_sha256,
            "fallback_report_sha256": self.fallback_report_sha256,
            "date_plan_fingerprint": self.date_plan.fingerprint,
            "expected_date_count": len(self.date_plan.expected_trade_dates),
            "expected_start_date": self.date_plan.start_date,
            "expected_end_date": self.date_plan.end_date,
            "recent_check_dates": list(self.recent_check_dates),
            "selected_asset_keys": list(self.selected_asset_keys),
            "registered_partition_count": self.registered_partition_count,
            "missing_registered_count": len(self.missing_registered_dates),
            "missing_registered_samples": list(self.missing_registered_dates[:_SAMPLE_LIMIT]),
            "active_run_count": self.active_run_count,
            "inventory_file_count": self.inventory_file_count,
            "inventory_row_count": self.inventory_row_count,
            "source_empty_raw_count": len(self.source_empty_raw_keys),
            "source_empty_raw_keys": list(self.source_empty_raw_keys),
            "inventory_elapsed_ms": round(self.inventory_elapsed_ms, 3),
            "assets": {
                value.spec.asset_key.to_user_string(): {
                    "layer": value.spec.layer,
                    "frequency": value.spec.frequency,
                    "file_count": len(value.files),
                    "row_count": sum(item.row_count for item in value.files),
                    "existing_materialization_count": len(
                        value.existing_materialized_dates
                    ),
                    "existing_ready_check_count": len(
                        value.existing_ready_check_dates
                    ),
                    "planned_materialization_count": (
                        value.planned_materialization_count
                    ),
                    "planned_check_count": value.planned_check_count,
                }
                for value in self.asset_plans
            },
            "planned_materialization_event_count": self.planned_materialization_count,
            "planned_check_event_count": self.planned_check_count,
            "planned_event_count": (
                self.planned_materialization_count + self.planned_check_count
            ),
            "precondition_errors": list(self.precondition_errors),
            "should_stop": self.should_stop,
        }


@dataclass(frozen=True, slots=True)
class MajorIndexMinsEventReport:
    mode: str
    confirmed: bool
    plan: MajorIndexMinsEventPlan
    selected_partition_keys: tuple[str, ...] = ()
    registered_partition_count: int = 0
    reported_materialization_count: int = 0
    reported_check_count: int = 0
    skipped_materialization_count: int = 0
    skipped_check_count: int = 0
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict[str, object]:
        selected_samples = tuple(
            dict.fromkeys(
                (
                    *self.selected_partition_keys[:3],
                    *self.selected_partition_keys[-3:],
                )
            )
        )
        return {
            "schema_version": 1,
            "mode": self.mode,
            "confirmed": self.confirmed,
            "selected_partition_count": len(self.selected_partition_keys),
            "selected_partition_start": (
                self.selected_partition_keys[0]
                if self.selected_partition_keys
                else None
            ),
            "selected_partition_end": (
                self.selected_partition_keys[-1]
                if self.selected_partition_keys
                else None
            ),
            "selected_partition_samples": list(selected_samples),
            "registered_partition_count": self.registered_partition_count,
            "reported_materialization_count": self.reported_materialization_count,
            "reported_check_count": self.reported_check_count,
            "reported_event_count": (
                self.reported_materialization_count + self.reported_check_count
            ),
            "skipped_materialization_count": self.skipped_materialization_count,
            "skipped_check_count": self.skipped_check_count,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "plan": self.plan.to_dict(),
        }


def _asset_specs() -> tuple[MajorIndexMinsEventAssetSpec, ...]:
    raw_columns = tuple(column.name for column in RAW_MAJOR_INDEX_MINS_SCHEMA)
    silver_columns = tuple(column.name for column in SILVER_MAJOR_INDEX_MINS_SCHEMA)
    return tuple(
        [
            MajorIndexMinsEventAssetSpec(
                layer="raw",
                frequency=frequency,
                asset_key=dg.AssetKey(asset_key),
                check_name=check_name,
                path_builder=raw_major_index_mins_path,
                observed_columns=raw_columns,
                source_method="tushare_major_index_mins_bootstrap",
            )
            for asset_key, check_name, frequency in zip(
                MAJOR_INDEX_MINS_RAW_ASSET_KEYS,
                MAJOR_INDEX_MINS_RAW_CHECKS,
                MAJOR_INDEX_MINS_SOURCE_FREQS,
                strict=True,
            )
        ]
        + [
            MajorIndexMinsEventAssetSpec(
                layer="silver",
                frequency=frequency,
                asset_key=dg.AssetKey(asset_key),
                check_name=check_name,
                path_builder=silver_major_index_mins_path,
                observed_columns=silver_columns,
                source_method="derived_major_index_mins_bootstrap",
            )
            for asset_key, check_name, frequency in zip(
                MAJOR_INDEX_MINS_SILVER_ASSET_KEYS,
                MAJOR_INDEX_MINS_SILVER_CHECKS,
                MAJOR_INDEX_MINS_SILVER_FREQS,
                strict=True,
            )
        ]
    )


def _load_json(path: Path, label: str) -> Mapping[str, Any]:
    if not path.is_file():
        raise MajorIndexMinsEventPlanError(f"missing {label}: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise MajorIndexMinsEventPlanError(f"invalid {label}: {path}") from error
    if not isinstance(value, Mapping):
        raise MajorIndexMinsEventPlanError(f"{label} must be a JSON object")
    return value


def _load_frozen_date_plan(
    *,
    connection: Any,
    lake_root: Path,
    report_path: Path,
) -> MajorIndexMinsDatePlan:
    report = _load_json(report_path, "P6 date-plan report")
    payload = report.get("date_plan")
    if not isinstance(payload, Mapping):
        raise MajorIndexMinsEventPlanError("P6 report has no date_plan")
    end_date = str(payload.get("end_date") or "")
    fingerprint = str(payload.get("fingerprint") or "")
    expected_count = int(payload.get("expected_date_count") or 0)
    if not end_date or not fingerprint or expected_count <= 0:
        raise MajorIndexMinsEventPlanError("P6 date_plan is incomplete")
    current = build_date_plan(
        connection=connection,
        lake_root=lake_root,
        end_date=end_date,
    )
    if current.fingerprint != fingerprint:
        raise MajorIndexMinsEventPlanError("P6 date-plan fingerprint no longer matches lake calendar")
    if len(current.expected_trade_dates) != expected_count:
        raise MajorIndexMinsEventPlanError("P6 date-plan count no longer matches lake calendar")
    return current


def _validate_promote_report(
    *,
    report_path: Path,
    lake_root: Path,
    date_plan: MajorIndexMinsDatePlan,
) -> tuple[Mapping[str, Any], str]:
    report = _load_json(report_path, "P7E promote report")
    expected_raw = len(date_plan.expected_trade_dates) * len(
        MAJOR_INDEX_MINS_SOURCE_FREQS
    )
    expected_silver = len(date_plan.expected_trade_dates) * len(
        MAJOR_INDEX_MINS_SILVER_FREQS
    )
    errors: list[str] = []
    if report.get("should_stop") is not False:
        errors.append("P7E promote report is not green")
    if Path(str(report.get("formal_lake_root", ""))).resolve() != lake_root.resolve():
        errors.append("P7E formal lake root mismatch")
    if report.get("date_plan_fingerprint") != date_plan.fingerprint:
        errors.append("P7E date-plan fingerprint mismatch")
    if int(report.get("post_raw_valid_count") or -1) != expected_raw:
        errors.append("P7E Raw valid file count mismatch")
    if int(report.get("post_silver_valid_count") or -1) != expected_silver:
        errors.append("P7E Silver valid file count mismatch")
    if int(report.get("post_raw_row_count") or 0) <= 0:
        errors.append("P7E Raw row count is not positive")
    if int(report.get("post_silver_row_count") or 0) <= 0:
        errors.append("P7E Silver row count is not positive")
    if report.get("failure_samples"):
        errors.append("P7E promote report contains failures")
    if report.get("stop_reason_codes"):
        errors.append("P7E promote report contains stop reasons")
    if errors:
        raise MajorIndexMinsEventPlanError("; ".join(errors))
    return report, hashlib.sha256(report_path.read_bytes()).hexdigest()


def _load_source_empty_raw_keys(
    *,
    report_path: Path,
    date_plan: MajorIndexMinsDatePlan,
) -> tuple[set[tuple[str, str]], str]:
    report = _load_json(report_path, "P7 fallback report")
    errors: list[str] = []
    if report.get("should_stop") is not False:
        errors.append("P7 fallback report is not green")
    if report.get("failure_samples"):
        errors.append("P7 fallback report contains failures")
    if report.get("stop_reason_codes"):
        errors.append("P7 fallback report contains stop reasons")
    results = report.get("results")
    if not isinstance(results, list):
        errors.append("P7 fallback report has no results list")
        results = []
    expected_dates = set(date_plan.expected_trade_dates)
    keys: set[tuple[str, str]] = set()
    for result in results:
        if not isinstance(result, Mapping):
            errors.append("P7 fallback result is not an object")
            continue
        trade_date = str(result.get("trade_date") or "")
        target_freq = str(result.get("target_freq") or "")
        key = (trade_date, target_freq)
        if trade_date not in expected_dates:
            errors.append(f"fallback date is outside frozen plan: {trade_date}")
        if target_freq not in MAJOR_INDEX_MINS_SOURCE_FREQS:
            errors.append(f"fallback frequency is not a Raw frequency: {target_freq}")
        if result.get("source_mode") != "derived_fallback":
            errors.append(f"fallback source mode is invalid: {key}")
        if not str(result.get("reason_code") or "").endswith("_source_empty"):
            errors.append(f"fallback reason does not prove source-empty: {key}")
        if key in keys:
            errors.append(f"duplicate fallback result: {key}")
        keys.add(key)
    if int(report.get("written_count") or 0) + int(report.get("reused_count") or 0) != len(keys):
        errors.append("P7 fallback result count mismatch")
    if errors:
        raise MajorIndexMinsEventPlanError("; ".join(errors))
    return keys, hashlib.sha256(report_path.read_bytes()).hexdigest()


def _expected_paths(
    *,
    lake_root: Path,
    date_plan: MajorIndexMinsDatePlan,
    spec: MajorIndexMinsEventAssetSpec,
) -> tuple[Path, ...]:
    return tuple(
        spec.path_builder(lake_root, spec.frequency, trade_date)
        for trade_date in date_plan.expected_trade_dates
    )


def _discovered_paths(lake_root: Path, spec: MajorIndexMinsEventAssetSpec) -> set[Path]:
    base = (
        lake_root / "raw" / "tushare" / "major_index_mins"
        if spec.layer == "raw"
        else lake_root / "silver" / "quote" / "major_index_mins"
    )
    return {
        value.resolve()
        for value in base.glob(
            f"freq={spec.frequency}/trade_date=*/part-000.parquet"
        )
    }


def _parquet_row_counts(connection: Any, paths: Sequence[Path]) -> dict[str, int]:
    if not paths:
        return {}
    rows = connection.execute(
        """
        SELECT file_name, sum(num_rows)::BIGINT
        FROM parquet_file_metadata(?)
        GROUP BY file_name
        """,
        [[str(value) for value in paths]],
    ).fetchall()
    return {
        str(Path(str(file_name)).resolve()): int(row_count or 0)
        for file_name, row_count in rows
    }


def _active_run_count(instance: dg.DagsterInstance) -> int:
    return len(
        instance.get_runs(
            filters=dg.RunsFilter(statuses=list(_ACTIVE_RUN_STATUSES)),
            limit=1,
        )
    )


def _materialization_records(
    *,
    instance: dg.DagsterInstance,
    asset_key: dg.AssetKey,
    partition_keys: Sequence[str],
) -> dict[str, object]:
    if not partition_keys:
        return {}
    result = instance.fetch_materializations(
        dg.AssetRecordsFilter(
            asset_key=asset_key,
            asset_partitions=list(partition_keys),
        ),
        limit=max(1, len(partition_keys)),
    )
    records: dict[str, object] = {}
    for record in result.records:
        partition_key = getattr(record, "partition_key", None)
        if partition_key is not None and partition_key not in records:
            records[str(partition_key)] = record
    return records


def _existing_ready_check_dates(
    *,
    instance: dg.DagsterInstance,
    spec: MajorIndexMinsEventAssetSpec,
    recent_dates: Sequence[str],
) -> tuple[str, ...]:
    materializations = _materialization_records(
        instance=instance,
        asset_key=spec.asset_key,
        partition_keys=recent_dates,
    )
    if not materializations:
        return ()
    latest_ids = {
        trade_date: getattr(record, "storage_id", None)
        for trade_date, record in materializations.items()
    }
    records = instance.event_log_storage.get_asset_check_execution_history(
        dg.AssetCheckKey(spec.asset_key, spec.check_name),
        limit=_CHECK_HISTORY_LIMIT,
    )
    ready: set[str] = set()
    selected = set(recent_dates)
    for record in records:
        partition_key = getattr(record, "partition", None)
        if partition_key not in selected or partition_key in ready:
            continue
        event = getattr(record, "event", None)
        dagster_event = getattr(event, "dagster_event", None) if event else None
        evaluation = (
            getattr(dagster_event, "event_specific_data", None)
            if dagster_event
            else None
        )
        target = getattr(evaluation, "target_materialization_data", None)
        if target is None or target.storage_id != latest_ids.get(partition_key):
            continue
        if (
            getattr(getattr(record, "status", None), "value", None) == "SUCCEEDED"
            and bool(getattr(evaluation, "blocking", False))
            and bool(getattr(evaluation, "passed", False))
        ):
            ready.add(str(partition_key))
    return tuple(sorted(ready))


def _selected_specs(asset_keys: Sequence[str] | None) -> tuple[MajorIndexMinsEventAssetSpec, ...]:
    specs = _asset_specs()
    if asset_keys is None:
        return specs
    requested = tuple(dict.fromkeys(str(value) for value in asset_keys))
    known = {value.asset_key.to_user_string(): value for value in specs}
    unknown = tuple(value for value in requested if value not in known)
    if unknown:
        raise MajorIndexMinsEventPlanError(
            "unknown major_index_mins asset keys: " + ",".join(unknown)
        )
    return tuple(known[value] for value in requested)


def plan_major_index_mins_bootstrap_events(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path,
    date_plan_report_path: Path,
    promote_report_path: Path,
    fallback_report_path: Path,
    duckdb_resource: DuckDBResource,
    selected_asset_keys: Sequence[str] | None = None,
    require_registered: bool = True,
) -> MajorIndexMinsEventPlan:
    started = perf_counter()
    selected_specs = _selected_specs(selected_asset_keys)
    precondition_errors: list[str] = []
    with duckdb_resource.connect() as connection:
        date_plan = _load_frozen_date_plan(
            connection=connection,
            lake_root=lake_root,
            report_path=date_plan_report_path,
        )
        promote_report, promote_sha256 = _validate_promote_report(
            report_path=promote_report_path,
            lake_root=lake_root,
            date_plan=date_plan,
        )
        source_empty_raw_keys, fallback_sha256 = _load_source_empty_raw_keys(
            report_path=fallback_report_path,
            date_plan=date_plan,
        )
        report_mtime = promote_report_path.stat().st_mtime
        recent_dates = date_plan.expected_trade_dates[-MAJOR_INDEX_MINS_EVENT_WINDOW_SIZE:]
        asset_plans: list[MajorIndexMinsEventAssetPlan] = []
        inventory_file_count = 0
        inventory_row_count = 0
        for spec in selected_specs:
            paths = _expected_paths(
                lake_root=lake_root,
                date_plan=date_plan,
                spec=spec,
            )
            expected_resolved = {value.resolve() for value in paths}
            discovered = _discovered_paths(lake_root, spec)
            missing = tuple(value for value in paths if not value.is_file())
            unexpected = tuple(sorted(discovered - expected_resolved))
            changed_after_report = tuple(
                value
                for value in paths
                if value.is_file() and value.stat().st_mtime > report_mtime
            )
            empty_files = tuple(
                value for value in paths if value.is_file() and value.stat().st_size <= 0
            )
            if missing:
                precondition_errors.append(
                    f"{spec.asset_key.to_user_string()} missing files={len(missing)}"
                )
            if unexpected:
                precondition_errors.append(
                    f"{spec.asset_key.to_user_string()} unexpected files={len(unexpected)}"
                )
            if changed_after_report:
                precondition_errors.append(
                    f"{spec.asset_key.to_user_string()} files changed after P7E={len(changed_after_report)}"
                )
            if empty_files:
                precondition_errors.append(
                    f"{spec.asset_key.to_user_string()} empty files={len(empty_files)}"
                )
            if missing or unexpected or changed_after_report or empty_files:
                row_counts: dict[str, int] = {}
            else:
                row_counts = _parquet_row_counts(connection, paths)
                if len(row_counts) != len(paths):
                    precondition_errors.append(
                        f"{spec.asset_key.to_user_string()} parquet metadata count mismatch"
                    )
            files: list[MajorIndexMinsEventFile] = []
            for trade_date, path in zip(
                date_plan.expected_trade_dates,
                paths,
                strict=True,
            ):
                row_count = row_counts.get(str(path.resolve()), 0)
                source_empty_exempt = (
                    spec.layer == "raw"
                    and (trade_date, spec.frequency) in source_empty_raw_keys
                )
                if row_counts and row_count <= 0 and not source_empty_exempt:
                    precondition_errors.append(
                        f"{spec.asset_key.to_user_string()} non-positive rows for {trade_date}"
                    )
                if row_counts and row_count > 0 and source_empty_exempt:
                    precondition_errors.append(
                        f"{spec.asset_key.to_user_string()} fallback evidence no longer matches {trade_date}"
                    )
                files.append(
                    MajorIndexMinsEventFile(
                        asset_key=spec.asset_key.to_user_string(),
                        partition_key=trade_date,
                        file_path=path,
                        row_count=row_count,
                        layer=spec.layer,
                        frequency=spec.frequency,
                        source_empty_exempt=source_empty_exempt,
                    )
                )
            inventory_file_count += len(files)
            inventory_row_count += sum(value.row_count for value in files)
            existing_materialized = tuple(
                sorted(
                    set(date_plan.expected_trade_dates)
                    & set(instance.get_materialized_partitions(spec.asset_key))
                )
            )
            existing_checks = _existing_ready_check_dates(
                instance=instance,
                spec=spec,
                recent_dates=recent_dates,
            )
            asset_plans.append(
                MajorIndexMinsEventAssetPlan(
                    spec=spec,
                    files=tuple(files),
                    recent_check_dates=recent_dates,
                    existing_materialized_dates=existing_materialized,
                    existing_ready_check_dates=existing_checks,
                )
            )

    expected_raw_rows = int(promote_report.get("post_raw_row_count") or 0)
    expected_silver_rows = int(promote_report.get("post_silver_row_count") or 0)
    if len(selected_specs) == len(_asset_specs()):
        if inventory_file_count != (
            len(date_plan.expected_trade_dates)
            * (len(MAJOR_INDEX_MINS_SOURCE_FREQS) + len(MAJOR_INDEX_MINS_SILVER_FREQS))
        ):
            precondition_errors.append("P8 inventory file count mismatch")
        if inventory_row_count != expected_raw_rows + expected_silver_rows:
            precondition_errors.append("P8 inventory row count does not match P7E")
        observed_source_empty_keys = {
            (value.partition_key, value.frequency)
            for asset_plan in asset_plans
            for value in asset_plan.files
            if value.source_empty_exempt
        }
        if observed_source_empty_keys != source_empty_raw_keys:
            precondition_errors.append("P8 source-empty Raw evidence mismatch")
        if any(
            trade_date in set(recent_dates)
            for trade_date, _frequency in source_empty_raw_keys
        ):
            precondition_errors.append(
                "recent-20 check window contains a source-empty Raw partition"
            )

    registered = {
        str(value)
        for value in instance.get_dynamic_partitions(MAJOR_INDEX_MINS_PARTITION_SET)
    }
    expected_set = set(date_plan.expected_trade_dates)
    unexpected_registered = tuple(sorted(registered - expected_set))
    if unexpected_registered:
        precondition_errors.append(
            "unexpected registered major_index_mins partitions: "
            + ",".join(unexpected_registered[:_SAMPLE_LIMIT])
        )
    missing_registered = tuple(sorted(expected_set - registered))
    if require_registered and missing_registered:
        precondition_errors.append(
            f"registered partition set is missing {len(missing_registered)} expected dates"
        )
    active_run_count = _active_run_count(instance)
    if active_run_count:
        precondition_errors.append("Dagster has active runs")
    return MajorIndexMinsEventPlan(
        lake_root=lake_root,
        date_plan_report_path=date_plan_report_path,
        promote_report_path=promote_report_path,
        fallback_report_path=fallback_report_path,
        date_plan=date_plan,
        recent_check_dates=recent_dates,
        selected_asset_keys=tuple(
            value.asset_key.to_user_string() for value in selected_specs
        ),
        asset_plans=tuple(asset_plans),
        registered_partition_count=len(registered),
        missing_registered_dates=missing_registered,
        active_run_count=active_run_count,
        p7e_report_sha256=promote_sha256,
        fallback_report_sha256=fallback_sha256,
        source_empty_raw_keys=tuple(
            f"{trade_date}:{frequency}"
            for trade_date, frequency in sorted(source_empty_raw_keys)
        ),
        inventory_file_count=inventory_file_count,
        inventory_row_count=inventory_row_count,
        inventory_elapsed_ms=(perf_counter() - started) * 1000,
        precondition_errors=tuple(dict.fromkeys(precondition_errors)),
    )


def register_major_index_mins_partitions(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path,
    date_plan_report_path: Path,
    promote_report_path: Path,
    fallback_report_path: Path,
    duckdb_resource: DuckDBResource,
    confirm_partition_write: bool,
) -> MajorIndexMinsEventReport:
    if not confirm_partition_write:
        raise ValueError("partition registration requires --confirm-partition-write")
    started = perf_counter()
    plan = plan_major_index_mins_bootstrap_events(
        instance=instance,
        lake_root=lake_root,
        date_plan_report_path=date_plan_report_path,
        promote_report_path=promote_report_path,
        fallback_report_path=fallback_report_path,
        duckdb_resource=duckdb_resource,
        require_registered=False,
    )
    if plan.precondition_errors:
        raise ValueError(
            "major_index_mins partition registration is blocked: "
            + "; ".join(plan.precondition_errors)
        )
    missing = list(plan.missing_registered_dates)
    if missing:
        instance.add_dynamic_partitions(MAJOR_INDEX_MINS_PARTITION_SET, missing)
    observed = {
        str(value)
        for value in instance.get_dynamic_partitions(MAJOR_INDEX_MINS_PARTITION_SET)
    }
    if observed != set(plan.date_plan.expected_trade_dates):
        raise RuntimeError("major_index_mins partition registration post-check failed")
    post_plan = replace(
        plan,
        registered_partition_count=len(observed),
        missing_registered_dates=(),
    )
    return MajorIndexMinsEventReport(
        mode="register-partitions",
        confirmed=True,
        plan=post_plan,
        registered_partition_count=len(observed),
        elapsed_ms=(perf_counter() - started) * 1000,
    )


def _report_materialization(
    *,
    instance: dg.DagsterInstance,
    plan: MajorIndexMinsEventPlan,
    asset_plan: MajorIndexMinsEventAssetPlan,
    file: MajorIndexMinsEventFile,
) -> None:
    instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset_key=asset_plan.spec.asset_key,
            partition=file.partition_key,
            metadata=build_materialization_metadata(
                uri=file.file_path,
                row_count=file.row_count,
                observed_columns=asset_plan.spec.observed_columns,
                extra_metadata={
                    "source_method": asset_plan.spec.source_method,
                    "bootstrap_event_backfill": True,
                    "event_backfill_scope": "full_history",
                    "partition_key": file.partition_key,
                    "frequency": file.frequency,
                    "date_plan_fingerprint": plan.date_plan.fingerprint,
                    "p7e_report_sha256": plan.p7e_report_sha256,
                    "p7e_report_path": str(plan.promote_report_path),
                    "fallback_report_sha256": plan.fallback_report_sha256,
                    "source_empty_exempt": file.source_empty_exempt,
                },
            ),
        )
    )


def _report_check(
    *,
    instance: dg.DagsterInstance,
    plan: MajorIndexMinsEventPlan,
    asset_plan: MajorIndexMinsEventAssetPlan,
    file: MajorIndexMinsEventFile,
    materialization: object,
) -> None:
    target = AssetCheckEvaluationTargetMaterializationData(
        storage_id=getattr(materialization, "storage_id"),
        run_id=getattr(materialization, "run_id"),
        timestamp=getattr(materialization, "timestamp"),
    )
    instance.report_runless_asset_event(
        dg.AssetCheckEvaluation(
            asset_key=asset_plan.spec.asset_key,
            check_name=asset_plan.spec.check_name,
            passed=True,
            blocking=True,
            partition=file.partition_key,
            target_materialization_data=target,
            metadata=build_check_metadata(
                check_scope=CheckScope.RECONCILIATION,
                checked_row_count=file.row_count,
                failed_row_count=0,
                file_path=file.file_path,
                extra_metadata={
                    "source_method": asset_plan.spec.source_method,
                    "bootstrap_event_backfill": True,
                    "event_backfill_scope": "recent_20_trade_days",
                    "partition_key": file.partition_key,
                    "frequency": file.frequency,
                    "reason_code": "ready",
                    "date_plan_fingerprint": plan.date_plan.fingerprint,
                    "p7e_report_sha256": plan.p7e_report_sha256,
                    "p7e_report_path": str(plan.promote_report_path),
                    "fallback_report_sha256": plan.fallback_report_sha256,
                },
            ),
        )
    )


def report_major_index_mins_events(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path,
    date_plan_report_path: Path,
    promote_report_path: Path,
    fallback_report_path: Path,
    duckdb_resource: DuckDBResource,
    dry_run: bool = True,
    confirm_event_write: bool = False,
    sample_only: bool = False,
    sample_date: str | None = None,
    selected_asset_keys: Sequence[str] | None = None,
    report_mode: str | None = None,
) -> MajorIndexMinsEventReport:
    if not dry_run and not confirm_event_write:
        raise ValueError("event apply requires --confirm-event-write")
    started = perf_counter()
    plan = plan_major_index_mins_bootstrap_events(
        instance=instance,
        lake_root=lake_root,
        date_plan_report_path=date_plan_report_path,
        promote_report_path=promote_report_path,
        fallback_report_path=fallback_report_path,
        duckdb_resource=duckdb_resource,
        selected_asset_keys=selected_asset_keys,
        require_registered=True,
    )
    if dry_run:
        return MajorIndexMinsEventReport(
            mode=report_mode or "dry-run",
            confirmed=False,
            plan=plan,
            registered_partition_count=plan.registered_partition_count,
            elapsed_ms=(perf_counter() - started) * 1000,
        )
    if plan.should_stop:
        raise ValueError(
            "major_index_mins event apply is blocked: "
            + "; ".join(plan.precondition_errors)
        )

    if sample_only:
        selected_date = sample_date or plan.recent_check_dates[-1]
        if selected_date not in plan.recent_check_dates:
            raise ValueError("sample date must be inside the recent-20 check window")
        selected_dates = (selected_date,)
    else:
        selected_dates = plan.date_plan.expected_trade_dates
    selected_date_set = set(selected_dates)
    recent_date_set = set(plan.recent_check_dates)
    reported_materializations = 0
    reported_checks = 0
    skipped_materializations = 0
    skipped_checks = 0
    total_reported = 0

    for asset_plan in plan.asset_plans:
        existing_materialized = set(asset_plan.existing_materialized_dates)
        selected_files = tuple(
            value for value in asset_plan.files if value.partition_key in selected_date_set
        )
        for file in selected_files:
            if file.partition_key in existing_materialized:
                skipped_materializations += 1
                continue
            _report_materialization(
                instance=instance,
                plan=plan,
                asset_plan=asset_plan,
                file=file,
            )
            existing_materialized.add(file.partition_key)
            reported_materializations += 1
            total_reported += 1
            if total_reported % MAJOR_INDEX_MINS_EVENT_PROGRESS_INTERVAL == 0:
                LOGGER.info("reported %s major_index_mins P8 events", total_reported)

        check_files = tuple(
            value for value in selected_files if value.partition_key in recent_date_set
        )
        existing_checks = set(asset_plan.existing_ready_check_dates)
        materializations = _materialization_records(
            instance=instance,
            asset_key=asset_plan.spec.asset_key,
            partition_keys=tuple(value.partition_key for value in check_files),
        )
        for file in check_files:
            if file.partition_key in existing_checks:
                skipped_checks += 1
                continue
            materialization = materializations.get(file.partition_key)
            if materialization is None:
                raise RuntimeError(
                    "missing target materialization for P8 check: "
                    f"{file.asset_key}:{file.partition_key}"
                )
            _report_check(
                instance=instance,
                plan=plan,
                asset_plan=asset_plan,
                file=file,
                materialization=materialization,
            )
            existing_checks.add(file.partition_key)
            reported_checks += 1
            total_reported += 1
            if total_reported % MAJOR_INDEX_MINS_EVENT_PROGRESS_INTERVAL == 0:
                LOGGER.info("reported %s major_index_mins P8 events", total_reported)

    return MajorIndexMinsEventReport(
        mode="sample" if sample_only else "apply",
        confirmed=True,
        plan=plan,
        selected_partition_keys=selected_dates,
        registered_partition_count=plan.registered_partition_count,
        reported_materialization_count=reported_materializations,
        reported_check_count=reported_checks,
        skipped_materialization_count=skipped_materializations,
        skipped_check_count=skipped_checks,
        elapsed_ms=(perf_counter() - started) * 1000,
    )


__all__ = [
    "MAJOR_INDEX_MINS_EVENT_WINDOW_SIZE",
    "MAJOR_INDEX_MINS_PARTITION_SET",
    "MajorIndexMinsEventPlan",
    "MajorIndexMinsEventPlanError",
    "MajorIndexMinsEventReport",
    "plan_major_index_mins_bootstrap_events",
    "register_major_index_mins_partitions",
    "report_major_index_mins_events",
]
