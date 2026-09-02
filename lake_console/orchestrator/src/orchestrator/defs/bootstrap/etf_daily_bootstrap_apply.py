"""Bounded sample and resumable file apply for ETF daily Bootstrap."""

from __future__ import annotations

import resource as process_resource
import shutil
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

from orchestrator.defs.bootstrap.etf_daily_bootstrap_plan import (
    EtfDailyBootstrapTarget,
    EtfDailyRawBootstrapPlan,
    EtfDailySilverBootstrapPlan,
    atomic_write_json,
    build_raw_manifest,
    hash_payload,
    inspect_targets,
    load_json,
    load_registered_bootstrap_dates,
    required_free_bytes,
    validate_roots,
    write_immutable_json,
)
from orchestrator.defs.io.etf_daily_raw_writer import (
    FUND_ADJ_RAW_SPEC,
    FUND_DAILY_RAW_SPEC,
    EtfDailyRawWriteResult,
    write_fund_adj_raw_partition,
    write_fund_daily_raw_partition,
)
from orchestrator.defs.io.etf_daily_silver_writer import (
    FUND_ADJ_SILVER_SPEC,
    FUND_DAILY_SILVER_SPEC,
    EtfDailySilverWriteResult,
    validate_etf_daily_basic_reference,
    write_etf_adj_factor_silver_partition,
    write_etf_daily_silver_partition,
)
from orchestrator.defs.paths import (
    raw_etf_basic_snapshot_path,
    silver_etf_basic_snapshot_path,
)
from orchestrator.defs.resources import DuckDBResource, TushareResource
from orchestrator.defs.run_contracts.etf_basic import (
    EtfBasicSilverSnapshotReference,
    build_etf_basic_silver_snapshot_reference,
)
from orchestrator.defs.run_contracts.etf_daily import (
    ETF_DAILY_BOOTSTRAP_BATCH_DAYS,
    ETF_DAILY_COVERAGE_POLICY_REVISION,
    FUND_ADJ_SOURCE_COLUMNS,
    FUND_DAILY_SOURCE_COLUMNS,
)


class EtfDailyBootstrapApplyError(ValueError):
    """Raised when a Bootstrap apply preflight or write cannot continue safely."""


@dataclass(frozen=True, slots=True)
class EtfDailyBootstrapCheckpointEntry:
    phase_plan_hash: str
    phase: Literal["raw", "silver", "events"]
    asset_key: str
    trade_date: str
    target_path: str
    content_hash: str
    row_count: int
    write_mode: str
    completed_at: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


RawWriter = Callable[..., EtfDailyRawWriteResult]
SilverWriter = Callable[..., EtfDailySilverWriteResult]


def load_checkpoint(path: Path) -> tuple[EtfDailyBootstrapCheckpointEntry, ...]:
    if not path.exists():
        return ()
    payload = load_json(path, label="ETF daily Bootstrap checkpoint")
    entries_payload = payload.get("entries")
    if not isinstance(entries_payload, list):
        raise EtfDailyBootstrapApplyError("checkpoint entries must be a list")
    expected_hash = hash_payload(entries_payload)
    if payload.get("checkpoint_hash") != expected_hash:
        raise EtfDailyBootstrapApplyError("checkpoint hash has drifted")
    try:
        entries = tuple(
            EtfDailyBootstrapCheckpointEntry(
                phase_plan_hash=str(item["phase_plan_hash"]),
                phase=str(item["phase"]),  # type: ignore[arg-type]
                asset_key=str(item["asset_key"]),
                trade_date=str(item["trade_date"]),
                target_path=str(item["target_path"]),
                content_hash=str(item["content_hash"]),
                row_count=int(item["row_count"]),
                write_mode=str(item["write_mode"]),
                completed_at=str(item["completed_at"]),
            )
            for item in entries_payload
        )
    except (KeyError, TypeError, ValueError) as error:
        raise EtfDailyBootstrapApplyError("checkpoint is structurally invalid") from error
    identities = {
        (item.phase, item.asset_key, item.trade_date, item.target_path)
        for item in entries
    }
    if len(identities) != len(entries) or any(
        item.phase not in {"raw", "silver", "events"} for item in entries
    ):
        raise EtfDailyBootstrapApplyError("checkpoint contains duplicate or invalid entries")
    return entries


def append_checkpoint(
    path: Path,
    *,
    entry: EtfDailyBootstrapCheckpointEntry,
) -> None:
    entries = list(load_checkpoint(path))
    identity = (entry.phase, entry.asset_key, entry.trade_date, entry.target_path)
    existing = next(
        (
            item
            for item in entries
            if (item.phase, item.asset_key, item.trade_date, item.target_path)
            == identity
        ),
        None,
    )
    if existing is not None:
        if existing != entry:
            raise EtfDailyBootstrapApplyError(
                f"checkpoint identity conflicts with existing entry: {identity}"
            )
        return
    entries.append(entry)
    payload_entries = [item.to_dict() for item in entries]
    atomic_write_json(
        path,
        {
            "schema_version": "etf_daily_bootstrap_checkpoint_v1",
            "entries": payload_entries,
            "checkpoint_hash": hash_payload(payload_entries),
        },
    )


def run_bounded_sample(
    *,
    raw_plan: EtfDailyRawBootstrapPlan,
    isolated_lake_root: Path,
    isolated_staging_root: Path,
    duckdb_resource: DuckDBResource,
    tushare: TushareResource,
    basic_reference: EtfBasicSilverSnapshotReference,
    output_path: Path,
) -> dict[str, object]:
    """Exercise all four public writers for at most first/middle/last dates."""

    validate_roots(isolated_lake_root, isolated_staging_root)
    dates = _sample_dates(raw_plan.trade_dates)
    if len(dates) > 3:
        raise EtfDailyBootstrapApplyError("bounded sample cannot exceed three dates")
    sample_reference = _copy_basic_reference(
        source_reference=basic_reference,
        isolated_lake_root=isolated_lake_root,
        duckdb_resource=duckdb_resource,
    )
    raw_results: list[EtfDailyRawWriteResult] = []
    silver_results: list[EtfDailySilverWriteResult] = []
    started = perf_counter()
    for trade_date in dates:
        raw_results.extend(
            _write_raw_pair(
                lake_root=isolated_lake_root,
                staging_root=isolated_staging_root,
                duckdb_resource=duckdb_resource,
                tushare=tushare,
                trade_date=trade_date,
                operation_id=f"{raw_plan.operation_id}-bounded-sample",
            )
        )
        silver_results.extend(
            _write_silver_pair(
                lake_root=isolated_lake_root,
                staging_root=isolated_staging_root,
                duckdb_resource=duckdb_resource,
                trade_date=trade_date,
                operation_id=f"{raw_plan.operation_id}-bounded-sample",
                basic_reference=sample_reference,
            )
        )
    with duckdb_resource.connect() as connection:
        temp_spill_bytes = int(
            connection.execute(
                "SELECT coalesce(sum(size), 0) FROM duckdb_temporary_files()"
            ).fetchone()[0]
            or 0
        )
    payload: dict[str, object] = {
        "schema_version": "etf_daily_bounded_sample_v1",
        "raw_plan_hash": raw_plan.raw_plan_hash,
        "trade_dates": list(dates),
        "raw_results": [item.to_details() for item in raw_results],
        "silver_results": [item.to_details() for item in silver_results],
        "request_count": sum(item.request_count for item in raw_results),
        "row_count": sum(item.written_row_count for item in raw_results),
        "max_file_size_bytes": max(
            (item.output_bytes for item in (*raw_results, *silver_results)),
            default=0,
        ),
        "elapsed_ms": round((perf_counter() - started) * 1000, 3),
        "peak_rss_bytes": _peak_rss_bytes(),
        "temp_spill_bytes": temp_spill_bytes,
        "basic_reference_fingerprint": sample_reference.reference_fingerprint,
        "field_gates": {
            "change": len(FUND_DAILY_SOURCE_COLUMNS) == 11
            and FUND_DAILY_SOURCE_COLUMNS[7] == "change",
            "discount_rate": "discount_rate" in FUND_ADJ_SOURCE_COLUMNS,
        },
        "formal_lake_files_written": 0,
        "dagster_events_written": 0,
    }
    payload["report_hash"] = hash_payload(payload)
    write_immutable_json(output_path, payload)
    return payload


def run_raw_apply(
    *,
    raw_plan: EtfDailyRawBootstrapPlan,
    instance: Any,
    lake_root: Path,
    staging_root: Path,
    duckdb_resource: DuckDBResource,
    tushare: TushareResource,
    checkpoint_path: Path,
    output_path: Path,
    confirm_raw_apply: bool,
) -> dict[str, object]:
    if not confirm_raw_apply:
        raise EtfDailyBootstrapApplyError("Raw apply confirmation is required")
    validate_roots(lake_root, staging_root)
    if raw_plan.should_stop:
        raise EtfDailyBootstrapApplyError("Raw Plan contains an invalid existing target")
    if load_registered_bootstrap_dates(instance) != raw_plan.trade_dates:
        raise EtfDailyBootstrapApplyError("registered dates or watermark drifted after Raw Plan")
    entries = load_checkpoint(checkpoint_path)
    _validate_phase_checkpoint(entries, phase="raw", plan_hash=raw_plan.raw_plan_hash)
    current = inspect_targets(
        duckdb_resource=duckdb_resource,
        lake_root=lake_root,
        trade_dates=raw_plan.trade_dates,
        specs=(FUND_DAILY_RAW_SPEC, FUND_ADJ_RAW_SPEC),
    )
    _validate_target_preflight(
        frozen=raw_plan.raw_targets,
        current=current,
        completed=entries,
        phase="raw",
    )
    _validate_space(staging_root, raw_plan.estimated_new_bytes)
    completed = {(item.asset_key, item.trade_date) for item in entries if item.phase == "raw"}
    started = perf_counter()
    for batch in _chunks(raw_plan.trade_dates, ETF_DAILY_BOOTSTRAP_BATCH_DAYS):
        for trade_date in batch:
            for writer, spec in (
                (write_fund_daily_raw_partition, FUND_DAILY_RAW_SPEC),
                (write_fund_adj_raw_partition, FUND_ADJ_RAW_SPEC),
            ):
                if (spec.asset_key, trade_date) in completed:
                    continue
                result = writer(
                    lake_root_path=lake_root,
                    staging_root_path=staging_root,
                    duckdb_resource=duckdb_resource,
                    tushare=tushare,
                    partition_key=trade_date,
                    operation_id=f"{raw_plan.operation_id}-raw-apply",
                )
                append_checkpoint(
                    checkpoint_path,
                    entry=_checkpoint_from_raw(raw_plan.raw_plan_hash, result),
                )
                completed.add((spec.asset_key, trade_date))
    payload = _apply_report(
        phase="raw",
        plan_hash=raw_plan.raw_plan_hash,
        checkpoint_path=checkpoint_path,
        expected_count=2 * len(raw_plan.trade_dates),
        elapsed_ms=(perf_counter() - started) * 1000,
    )
    atomic_write_json(output_path, payload)
    return payload


def run_silver_apply(
    *,
    silver_plan: EtfDailySilverBootstrapPlan,
    raw_plan: EtfDailyRawBootstrapPlan,
    latest_basic_reference: EtfBasicSilverSnapshotReference,
    lake_root: Path,
    staging_root: Path,
    duckdb_resource: DuckDBResource,
    checkpoint_path: Path,
    output_path: Path,
    confirm_silver_apply: bool,
) -> dict[str, object]:
    if not confirm_silver_apply:
        raise EtfDailyBootstrapApplyError("Silver apply confirmation is required")
    validate_roots(lake_root, staging_root)
    if silver_plan.should_stop:
        raise EtfDailyBootstrapApplyError("Silver Plan contains an invalid existing target")
    if silver_plan.parent_raw_plan_hash != raw_plan.raw_plan_hash:
        raise EtfDailyBootstrapApplyError("Silver Plan parent Raw hash does not match")
    if silver_plan.coverage_policy_revision != ETF_DAILY_COVERAGE_POLICY_REVISION:
        raise EtfDailyBootstrapApplyError("coverage policy revision drifted")
    latest = validate_etf_daily_basic_reference(
        lake_root_path=lake_root,
        duckdb_resource=duckdb_resource,
        basic_reference=latest_basic_reference,
    )
    if latest.reference_fingerprint != silver_plan.basic_reference.reference_fingerprint:
        raise EtfDailyBootstrapApplyError("latest ready Basic changed after Silver Plan")
    manifest = build_raw_manifest(
        raw_plan=raw_plan,
        lake_root=lake_root,
        duckdb_resource=duckdb_resource,
    )
    if hash_payload([item.to_dict() for item in manifest]) != silver_plan.raw_manifest_hash:
        raise EtfDailyBootstrapApplyError("Raw manifest drifted after Silver Plan")
    entries = load_checkpoint(checkpoint_path)
    _validate_phase_checkpoint(entries, phase="silver", plan_hash=silver_plan.silver_plan_hash)
    current = inspect_targets(
        duckdb_resource=duckdb_resource,
        lake_root=lake_root,
        trade_dates=silver_plan.trade_dates,
        specs=(FUND_DAILY_SILVER_SPEC, FUND_ADJ_SILVER_SPEC),
    )
    _validate_target_preflight(
        frozen=silver_plan.silver_targets,
        current=current,
        completed=entries,
        phase="silver",
    )
    _validate_space(staging_root, silver_plan.estimated_new_bytes)
    completed = {(item.asset_key, item.trade_date) for item in entries if item.phase == "silver"}
    started = perf_counter()
    for batch in _chunks(silver_plan.trade_dates, ETF_DAILY_BOOTSTRAP_BATCH_DAYS):
        for trade_date in batch:
            for writer, spec in (
                (write_etf_daily_silver_partition, FUND_DAILY_SILVER_SPEC),
                (write_etf_adj_factor_silver_partition, FUND_ADJ_SILVER_SPEC),
            ):
                if (spec.asset_key, trade_date) in completed:
                    continue
                result = writer(
                    lake_root_path=lake_root,
                    staging_root_path=staging_root,
                    duckdb_resource=duckdb_resource,
                    partition_key=trade_date,
                    operation_id=f"{silver_plan.operation_id}-silver-apply",
                    basic_reference=latest,
                )
                append_checkpoint(
                    checkpoint_path,
                    entry=_checkpoint_from_silver(silver_plan.silver_plan_hash, result),
                )
                completed.add((spec.asset_key, trade_date))
    payload = _apply_report(
        phase="silver",
        plan_hash=silver_plan.silver_plan_hash,
        checkpoint_path=checkpoint_path,
        expected_count=2 * len(silver_plan.trade_dates),
        elapsed_ms=(perf_counter() - started) * 1000,
    )
    atomic_write_json(output_path, payload)
    return payload


def _copy_basic_reference(
    *,
    source_reference: EtfBasicSilverSnapshotReference,
    isolated_lake_root: Path,
    duckdb_resource: DuckDBResource,
) -> EtfBasicSilverSnapshotReference:
    source = source_reference.validate_contract()
    raw_target = raw_etf_basic_snapshot_path(isolated_lake_root, source.raw_snapshot_hash)
    silver_target = silver_etf_basic_snapshot_path(isolated_lake_root, source.raw_snapshot_hash)
    for source_path, target_path in (
        (Path(source.raw_uri), raw_target),
        (Path(source.silver_uri), silver_target),
    ):
        if not source_path.is_file():
            raise EtfDailyBootstrapApplyError(f"Basic sample source is missing: {source_path}")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists():
            raise EtfDailyBootstrapApplyError(f"Basic sample target already exists: {target_path}")
        shutil.copy2(source_path, target_path)
    copied = build_etf_basic_silver_snapshot_reference(
        raw_snapshot_hash=source.raw_snapshot_hash,
        silver_content_hash=source.silver_content_hash,
        raw_uri=str(raw_target),
        silver_uri=str(silver_target),
        raw_observed_at=source.raw_observed_at,
        silver_observed_at=source.silver_observed_at,
        eligibility_as_of=source.eligibility_as_of,
        requestable_code_count=source.requestable_code_count,
        requestable_code_hash=source.requestable_code_hash,
    )
    return validate_etf_daily_basic_reference(
        lake_root_path=isolated_lake_root,
        duckdb_resource=duckdb_resource,
        basic_reference=copied,
    )


def _sample_dates(dates: Sequence[str]) -> tuple[str, ...]:
    if not dates:
        raise EtfDailyBootstrapApplyError("bounded sample requires at least one date")
    return tuple(dict.fromkeys((dates[0], dates[len(dates) // 2], dates[-1])))


def _peak_rss_bytes() -> int:
    peak = int(process_resource.getrusage(process_resource.RUSAGE_SELF).ru_maxrss)
    return peak if sys.platform == "darwin" else peak * 1024


def _write_raw_pair(
    *,
    lake_root: Path,
    staging_root: Path,
    duckdb_resource: DuckDBResource,
    tushare: TushareResource,
    trade_date: str,
    operation_id: str,
) -> tuple[EtfDailyRawWriteResult, EtfDailyRawWriteResult]:
    common: dict[str, Any] = {
        "lake_root_path": lake_root,
        "staging_root_path": staging_root,
        "duckdb_resource": duckdb_resource,
        "tushare": tushare,
        "partition_key": trade_date,
        "operation_id": operation_id,
    }
    return (
        write_fund_daily_raw_partition(**common),
        write_fund_adj_raw_partition(**common),
    )


def _write_silver_pair(
    *,
    lake_root: Path,
    staging_root: Path,
    duckdb_resource: DuckDBResource,
    trade_date: str,
    operation_id: str,
    basic_reference: EtfBasicSilverSnapshotReference,
) -> tuple[EtfDailySilverWriteResult, EtfDailySilverWriteResult]:
    common: dict[str, Any] = {
        "lake_root_path": lake_root,
        "staging_root_path": staging_root,
        "duckdb_resource": duckdb_resource,
        "partition_key": trade_date,
        "operation_id": operation_id,
        "basic_reference": basic_reference,
    }
    return (
        write_etf_daily_silver_partition(**common),
        write_etf_adj_factor_silver_partition(**common),
    )


def _chunks(values: Sequence[str], size: int) -> tuple[tuple[str, ...], ...]:
    return tuple(tuple(values[index : index + size]) for index in range(0, len(values), size))


def _validate_space(staging_root: Path, estimated_bytes: int) -> None:
    required = required_free_bytes(estimated_bytes)
    free = shutil.disk_usage(staging_root).free
    if free < required:
        raise EtfDailyBootstrapApplyError(
            f"Bootstrap apply space gate failed: required={required}, free={free}"
        )


def _validate_phase_checkpoint(
    entries: Sequence[EtfDailyBootstrapCheckpointEntry],
    *,
    phase: str,
    plan_hash: str,
) -> None:
    if any(item.phase == phase and item.phase_plan_hash != plan_hash for item in entries):
        raise EtfDailyBootstrapApplyError(f"{phase} checkpoint belongs to another plan")


def _validate_target_preflight(
    *,
    frozen: Sequence[EtfDailyBootstrapTarget],
    current: Sequence[EtfDailyBootstrapTarget],
    completed: Sequence[EtfDailyBootstrapCheckpointEntry],
    phase: str,
) -> None:
    current_by_key = {(item.asset_key, item.trade_date): item for item in current}
    checkpoint_by_key = {
        (item.asset_key, item.trade_date): item for item in completed if item.phase == phase
    }
    for target in frozen:
        key = (target.asset_key, target.trade_date)
        observed = current_by_key.get(key)
        if observed is None or observed.target_path != target.target_path:
            raise EtfDailyBootstrapApplyError(f"target scope drifted: {key}")
        checkpoint = checkpoint_by_key.get(key)
        if checkpoint is not None:
            if (
                observed.observed_state != "existing_structurally_ready"
                or checkpoint.target_path != observed.target_path
                or checkpoint.row_count != observed.observed_row_count
                or checkpoint.content_hash != observed.observed_content_hash
            ):
                raise EtfDailyBootstrapApplyError(f"completed target drifted: {key}")
        elif target.observed_state == "missing":
            if observed.observed_state == "existing_invalid":
                raise EtfDailyBootstrapApplyError(
                    f"uncompleted target became invalid after plan: {key}"
                )
            # A process can stop after os.replace() and before its checkpoint.
            # Re-running the public writer safely proves equivalence or conflict.
            continue
        elif target != observed:
            raise EtfDailyBootstrapApplyError(f"uncompleted target changed after plan: {key}")


def _checkpoint_from_raw(
    plan_hash: str, result: EtfDailyRawWriteResult
) -> EtfDailyBootstrapCheckpointEntry:
    return EtfDailyBootstrapCheckpointEntry(
        plan_hash,
        "raw",
        result.asset_key,
        result.partition_key,
        str(result.target_path),
        result.content_hash,
        result.written_row_count,
        result.write_mode,
        datetime.now().astimezone().isoformat(),
    )


def _checkpoint_from_silver(
    plan_hash: str, result: EtfDailySilverWriteResult
) -> EtfDailyBootstrapCheckpointEntry:
    return EtfDailyBootstrapCheckpointEntry(
        plan_hash,
        "silver",
        result.asset_key,
        result.partition_key,
        str(result.target_path),
        result.content_hash,
        result.written_row_count,
        result.write_mode,
        datetime.now().astimezone().isoformat(),
    )


def _apply_report(
    *,
    phase: str,
    plan_hash: str,
    checkpoint_path: Path,
    expected_count: int,
    elapsed_ms: float,
) -> dict[str, object]:
    entries = [item for item in load_checkpoint(checkpoint_path) if item.phase == phase]
    if len(entries) != expected_count:
        raise EtfDailyBootstrapApplyError(
            f"{phase} checkpoint is incomplete: expected={expected_count}, actual={len(entries)}"
        )
    payload: dict[str, object] = {
        "schema_version": f"etf_daily_{phase}_apply_v1",
        "phase_plan_hash": plan_hash,
        "checkpoint_path": str(checkpoint_path),
        "completed_file_count": len(entries),
        "expected_file_count": expected_count,
        "elapsed_ms": round(elapsed_ms, 3),
        "dagster_events_written": 0,
    }
    payload["report_hash"] = hash_payload(payload)
    return payload


__all__ = [
    "EtfDailyBootstrapApplyError",
    "EtfDailyBootstrapCheckpointEntry",
    "append_checkpoint",
    "load_checkpoint",
    "run_bounded_sample",
    "run_raw_apply",
    "run_silver_apply",
]
