"""Reviewed, resumable direct-Lake bootstrap for stock daily trend channels."""

from __future__ import annotations

import hashlib
import json
import math
import os
import resource
import shutil
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from orchestrator.defs.asset_guards.stock_daily_trend_channel_lake_readiness import (
    StockDailyTrendChannelHistorySegmentAudit,
    audit_stock_daily_trend_channel_history_segment,
)
from orchestrator.defs.duckdb_connection import (
    DEFAULT_DUCKDB_CONNECTION_SETTINGS,
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    DEFAULT_LAKE_STAGING_ROOT,
    gold_stock_daily_qfq_path,
    gold_stock_daily_trend_channel_path,
    gold_stock_daily_trend_channel_staging_path,
    gold_stock_daily_trend_channel_state_path,
    gold_stock_daily_trend_channel_state_staging_path,
    silver_stock_lifecycle_path,
)
from orchestrator.defs.stock_daily_trend_channel import (
    DAILY_TEMP_SPILL_HARD_LIMIT_BYTES,
    FORMULA_VERSION,
    SEGMENT_TRADE_DAY_LIMIT,
    build_stock_daily_trend_channel_history_segment_sql,
)

PLAN_SCHEMA_VERSION = 1
PLAN_PHASE = "stock_daily_trend_channel_history_plan"
CHECKPOINT_PHASE = "stock_daily_trend_channel_history_checkpoint"
AUDIT_PHASE = "stock_daily_trend_channel_history_file_audit"
PROMOTE_PHASE = "stock_daily_trend_channel_history_promotion"
FINAL_AUDIT_PHASE = "stock_daily_trend_channel_history_final_audit"

RESULT_ASSET_KEY = "gold_stock_daily_trend_channel"
STATE_ASSET_KEY = "gold_stock_daily_trend_channel_state"
BOOTSTRAP_HISTORY_PARTITION_LIMIT = 10_000
BOOTSTRAP_DAILY_QFQ_ROW_LIMIT = 6_500
BOOTSTRAP_CHECK_EVENT_PARTITION_LIMIT = 21
BOOTSTRAP_ORDINARY_CHECK_COUNT = 3
BOOTSTRAP_MAX_SEGMENTS_PER_PROCESS = 13
BOOTSTRAP_M0_REFERENCE_QFQ_ROWS = 11_710_697
BOOTSTRAP_M0_REFERENCE_CANDIDATE_BYTES = 1_253_938_232
BOOTSTRAP_REPORT_SAMPLE_LIMIT = 20


class StockDailyTrendChannelHistoryError(RuntimeError):
    """Fail-closed error for the reviewed history bootstrap."""


@dataclass(frozen=True, slots=True)
class StockDailyTrendChannelHistorySourceFile:
    trade_date: str
    path: Path
    size_bytes: int
    sha256: str
    row_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "trade_date": self.trade_date,
            "path": str(self.path),
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "row_count": self.row_count,
        }


@dataclass(frozen=True, slots=True)
class StockDailyTrendChannelHistorySegment:
    segment_index: int
    trade_dates: tuple[str, ...]
    source_files: tuple[StockDailyTrendChannelHistorySourceFile, ...]

    @property
    def start_date(self) -> str:
        return self.trade_dates[0]

    @property
    def end_date(self) -> str:
        return self.trade_dates[-1]

    @property
    def source_row_count(self) -> int:
        return sum(value.row_count for value in self.source_files)

    def to_dict(self) -> dict[str, object]:
        return {
            "segment_index": self.segment_index,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "trade_dates": list(self.trade_dates),
            "source_files": [value.to_dict() for value in self.source_files],
            "source_row_count": self.source_row_count,
        }


@dataclass(frozen=True, slots=True)
class StockDailyTrendChannelHistoryPlan:
    report_path: Path
    plan_id: str
    plan_hash: str
    lake_root: Path
    staging_root: Path
    lifecycle_path: Path
    lifecycle_sha256: str
    segments: tuple[StockDailyTrendChannelHistorySegment, ...]
    stop_reasons: tuple[str, ...]
    report: Mapping[str, object]

    @property
    def trade_dates(self) -> tuple[str, ...]:
        return tuple(
            trade_date
            for segment in self.segments
            for trade_date in segment.trade_dates
        )

    @property
    def should_stop(self) -> bool:
        return bool(self.stop_reasons)


@dataclass(frozen=True, slots=True)
class _GeneratedFile:
    asset_key: str
    trade_date: str
    candidate_path: Path
    target_path: Path
    row_count: int
    size_bytes: int
    sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "asset_key": self.asset_key,
            "trade_date": self.trade_date,
            "candidate_path": str(self.candidate_path),
            "target_path": str(self.target_path),
            "row_count": self.row_count,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


def plan_stock_daily_trend_channel_history(
    *,
    lake_root: Path = Path(DEFAULT_LAKE_ROOT),
    staging_root: Path = Path(DEFAULT_LAKE_STAGING_ROOT),
    output_dir: Path = Path("/private/tmp"),
    duckdb_settings: DuckDBConnectionSettings = DEFAULT_DUCKDB_CONNECTION_SETTINGS,
) -> StockDailyTrendChannelHistoryPlan:
    """Write a read-only frozen plan derived from every formal qfq partition."""

    started_at = time.perf_counter()
    root = Path(lake_root).resolve()
    staging = Path(staging_root).resolve()
    lifecycle_path = silver_stock_lifecycle_path(root)
    discovered = _discover_qfq_files(root)
    stop_reasons: list[str] = []
    if not discovered:
        stop_reasons.append("qfq_partitions_missing")
    if len(discovered) > BOOTSTRAP_HISTORY_PARTITION_LIMIT:
        stop_reasons.append("qfq_partition_limit_exceeded")
    if not lifecycle_path.is_file():
        stop_reasons.append("stock_lifecycle_missing")
    if not staging.is_dir():
        stop_reasons.append("staging_root_missing")
    if staging == root or staging.is_relative_to(root):
        stop_reasons.append("staging_root_inside_formal_lake")
    if (
        staging.is_dir()
        and root.is_dir()
        and staging.stat().st_dev != root.stat().st_dev
    ):
        stop_reasons.append("staging_and_formal_not_same_filesystem")

    row_counts: dict[str, int] = {}
    distinct_code_count = 0
    delisted_history_code_count = 0
    lifecycle_missing_code_count = 0
    qfq_trade_date_mismatch_count = 0
    if discovered and lifecycle_path.is_file():
        with connect_configured_duckdb(duckdb_settings) as connection:
            (
                row_counts,
                distinct_code_count,
                delisted_history_code_count,
                lifecycle_missing_code_count,
                qfq_trade_date_mismatch_count,
            ) = _profile_qfq_history(
                connection=connection,
                discovered=discovered,
                lifecycle_path=lifecycle_path,
            )
    if qfq_trade_date_mismatch_count:
        stop_reasons.append("qfq_partition_trade_date_mismatch")
    if lifecycle_missing_code_count:
        stop_reasons.append("qfq_code_missing_lifecycle")
    if row_counts and max(row_counts.values()) > BOOTSTRAP_DAILY_QFQ_ROW_LIMIT:
        stop_reasons.append("daily_qfq_row_limit_exceeded")
    if row_counts and any(value <= 0 for value in row_counts.values()):
        stop_reasons.append("empty_qfq_partition")

    source_files = tuple(
        StockDailyTrendChannelHistorySourceFile(
            trade_date=trade_date,
            path=path,
            size_bytes=path.stat().st_size,
            sha256=_file_sha256(path),
            row_count=row_counts.get(trade_date, 0),
        )
        for trade_date, path in discovered
    )
    segments = tuple(
        StockDailyTrendChannelHistorySegment(
            segment_index=index + 1,
            trade_dates=tuple(value.trade_date for value in selected),
            source_files=selected,
        )
        for index, start in enumerate(
            range(0, len(source_files), SEGMENT_TRADE_DAY_LIMIT)
        )
        if (selected := source_files[start : start + SEGMENT_TRADE_DAY_LIMIT])
    )
    target_conflicts = tuple(
        path
        for trade_date, _ in discovered
        for path in (
            gold_stock_daily_trend_channel_path(root, trade_date),
            gold_stock_daily_trend_channel_state_path(root, trade_date),
        )
        if path.exists()
    )
    if target_conflicts:
        stop_reasons.append("target_files_already_exist")
    qfq_row_count = sum(row_counts.values())
    estimated_candidate_bytes = math.ceil(
        qfq_row_count
        * BOOTSTRAP_M0_REFERENCE_CANDIDATE_BYTES
        / BOOTSTRAP_M0_REFERENCE_QFQ_ROWS
    )
    estimated_temp_bytes = DAILY_TEMP_SPILL_HARD_LIMIT_BYTES
    required_staging_bytes = 2 * estimated_candidate_bytes + estimated_temp_bytes
    formal_free_bytes = shutil.disk_usage(root).free if root.is_dir() else 0
    staging_free_bytes = shutil.disk_usage(staging).free if staging.is_dir() else 0
    if staging.is_dir() and staging_free_bytes < required_staging_bytes:
        stop_reasons.append("staging_space_insufficient")
    if root.is_dir() and formal_free_bytes < estimated_candidate_bytes:
        stop_reasons.append("formal_lake_space_insufficient")

    plan_id = uuid.uuid4().hex
    normalized_stop_reasons = tuple(sorted(set(stop_reasons)))
    lifecycle_sha256 = _file_sha256(lifecycle_path) if lifecycle_path.is_file() else ""
    payload = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "phase": PLAN_PHASE,
        "plan_id": plan_id,
        "lake_root": str(root),
        "staging_root": str(staging),
        "formula_version": FORMULA_VERSION,
        "segment_trade_day_limit": SEGMENT_TRADE_DAY_LIMIT,
        "lifecycle_path": str(lifecycle_path),
        "lifecycle_sha256": lifecycle_sha256,
        "segments": [segment.to_dict() for segment in segments],
        "stop_reasons": list(normalized_stop_reasons),
    }
    plan_hash = _hash_payload(payload)
    trade_dates = tuple(value.trade_date for value in source_files)
    report = {
        **payload,
        "plan_hash": plan_hash,
        "read_only": True,
        "qfq_min_trade_date": trade_dates[0] if trade_dates else None,
        "qfq_max_trade_date": trade_dates[-1] if trade_dates else None,
        "qfq_partition_count": len(trade_dates),
        "qfq_file_count": len(source_files),
        "qfq_row_count": qfq_row_count,
        "distinct_ts_code_count": distinct_code_count,
        "delisted_history_code_count": delisted_history_code_count,
        "lifecycle_missing_code_count": lifecycle_missing_code_count,
        "target_partition_count": len(trade_dates),
        "target_result_file_count": len(trade_dates),
        "target_state_file_count": len(trade_dates),
        "conflicting_target_file_count": len(target_conflicts),
        "conflicting_target_file_samples": [
            str(value) for value in target_conflicts[:BOOTSTRAP_REPORT_SAMPLE_LIMIT]
        ],
        "estimated_candidate_bytes": estimated_candidate_bytes,
        "estimated_duckdb_temp_bytes": estimated_temp_bytes,
        "required_staging_free_bytes": required_staging_bytes,
        "formal_free_bytes": formal_free_bytes,
        "staging_free_bytes": staging_free_bytes,
        "estimated_materialization_event_count": 2 * len(trade_dates),
        "estimated_check_event_count": (
            min(len(trade_dates), BOOTSTRAP_CHECK_EVENT_PARTITION_LIMIT)
            * BOOTSTRAP_ORDINARY_CHECK_COUNT
        ),
        "segment_count": len(segments),
        "should_stop": bool(normalized_stop_reasons),
        "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 3),
    }
    output = Path(output_dir).resolve()
    _assert_report_directory(output, lake_root=root, staging_root=staging)
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / f"stock_daily_trend_channel_history_plan_{plan_id}.json"
    _write_json_atomic(report_path, report)
    return StockDailyTrendChannelHistoryPlan(
        report_path=report_path,
        plan_id=plan_id,
        plan_hash=plan_hash,
        lake_root=root,
        staging_root=staging,
        lifecycle_path=lifecycle_path,
        lifecycle_sha256=lifecycle_sha256,
        segments=segments,
        stop_reasons=normalized_stop_reasons,
        report=report,
    )


def load_stock_daily_trend_channel_history_plan(
    report_path: Path,
) -> StockDailyTrendChannelHistoryPlan:
    """Load and cryptographically verify one frozen plan report."""

    normalized_path = Path(report_path).resolve()
    report = _load_json(normalized_path, label="trend-channel history plan")
    if (
        report.get("schema_version") != PLAN_SCHEMA_VERSION
        or report.get("phase") != PLAN_PHASE
        or report.get("read_only") is not True
        or report.get("formula_version") != FORMULA_VERSION
        or report.get("segment_trade_day_limit") != SEGMENT_TRADE_DAY_LIMIT
    ):
        raise StockDailyTrendChannelHistoryError("history plan contract is invalid")
    segments = tuple(_load_segment(value) for value in report.get("segments", ()))
    stop_reasons = tuple(str(value) for value in report.get("stop_reasons", ()))
    payload = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "phase": PLAN_PHASE,
        "plan_id": str(report.get("plan_id", "")),
        "lake_root": str(Path(str(report.get("lake_root", ""))).resolve()),
        "staging_root": str(Path(str(report.get("staging_root", ""))).resolve()),
        "formula_version": FORMULA_VERSION,
        "segment_trade_day_limit": SEGMENT_TRADE_DAY_LIMIT,
        "lifecycle_path": str(Path(str(report.get("lifecycle_path", ""))).resolve()),
        "lifecycle_sha256": str(report.get("lifecycle_sha256", "")),
        "segments": [segment.to_dict() for segment in segments],
        "stop_reasons": list(stop_reasons),
    }
    plan_hash = _hash_payload(payload)
    if report.get("plan_hash") != plan_hash:
        raise StockDailyTrendChannelHistoryError("history plan hash drifted")
    plan = StockDailyTrendChannelHistoryPlan(
        report_path=normalized_path,
        plan_id=str(report.get("plan_id", "")),
        plan_hash=plan_hash,
        lake_root=Path(payload["lake_root"]),
        staging_root=Path(payload["staging_root"]),
        lifecycle_path=Path(payload["lifecycle_path"]),
        lifecycle_sha256=str(payload["lifecycle_sha256"]),
        segments=segments,
        stop_reasons=stop_reasons,
        report=report,
    )
    _validate_plan_structure(plan)
    return plan


def generate_stock_daily_trend_channel_history(
    *,
    plan: StockDailyTrendChannelHistoryPlan,
    expected_plan_id: str,
    expected_plan_hash: str,
    expected_start_date: str,
    expected_end_date: str,
    checkpoint_path: Path,
    dry_run: bool = True,
    confirm_write: bool = False,
    segment_count_limit: int = 1,
    duckdb_settings: DuckDBConnectionSettings = DEFAULT_DUCKDB_CONNECTION_SETTINGS,
) -> dict[str, object]:
    """Generate a bounded prefix of reviewed candidates and checkpoint it."""

    _assert_apply_contract(
        plan=plan,
        expected_plan_id=expected_plan_id,
        expected_plan_hash=expected_plan_hash,
        expected_start_date=expected_start_date,
        expected_end_date=expected_end_date,
    )
    if not 1 <= segment_count_limit <= BOOTSTRAP_MAX_SEGMENTS_PER_PROCESS:
        raise StockDailyTrendChannelHistoryError(
            "segment_count_limit is outside the reviewed process bound"
        )
    normalized_checkpoint = _validated_staging_file(
        checkpoint_path,
        staging_root=plan.staging_root,
        label="history checkpoint",
    )
    if dry_run:
        return {
            "mode": "dry-run",
            "plan_id": plan.plan_id,
            "plan_hash": plan.plan_hash,
            "selected_segment_count": min(segment_count_limit, len(plan.segments)),
            "candidate_file_count": 0,
            "formal_file_count": 0,
        }
    if not confirm_write:
        raise StockDailyTrendChannelHistoryError(
            "history generation requires confirm_write=True"
        )
    _validate_lifecycle_identity(plan)
    _assert_current_disk_capacity(plan)
    completed = _load_checkpoint(normalized_checkpoint, plan=plan)
    processed = 0
    for segment in plan.segments:
        segment_key = str(segment.segment_index)
        _validate_segment_sources(segment)
        existing = completed.get(segment_key)
        if existing is not None and _checkpoint_segment_is_trusted(
            existing,
            plan=plan,
            segment=segment,
        ):
            continue
        completed.pop(segment_key, None)
        if processed >= segment_count_limit:
            break
        generated, audit, temp_spill_bytes, elapsed_ms = _generate_history_segment(
            plan=plan,
            segment=segment,
            duckdb_settings=duckdb_settings,
        )
        completed[segment_key] = {
            "segment_index": segment.segment_index,
            "start_date": segment.start_date,
            "end_date": segment.end_date,
            "files": [value.to_dict() for value in generated],
            "audit": _segment_audit_dict(audit),
            "temp_spill_bytes": temp_spill_bytes,
            "elapsed_ms": elapsed_ms,
            "completed_at": datetime.now(UTC).isoformat(),
        }
        _write_checkpoint(normalized_checkpoint, plan=plan, completed=completed)
        processed += 1
    return {
        "mode": "apply",
        "plan_id": plan.plan_id,
        "plan_hash": plan.plan_hash,
        "processed_segment_count": processed,
        "completed_segment_count": len(completed),
        "remaining_segment_count": len(plan.segments) - len(completed),
        "checkpoint_path": str(normalized_checkpoint),
        "formal_file_count": 0,
    }


def audit_stock_daily_trend_channel_history_candidates(
    *,
    plan: StockDailyTrendChannelHistoryPlan,
    expected_plan_id: str,
    expected_plan_hash: str,
    expected_start_date: str,
    expected_end_date: str,
    checkpoint_path: Path,
    output_path: Path,
    duckdb_settings: DuckDBConnectionSettings = DEFAULT_DUCKDB_CONNECTION_SETTINGS,
) -> dict[str, object]:
    """Re-audit every candidate segment using bounded set-based queries."""

    _assert_apply_contract(
        plan=plan,
        expected_plan_id=expected_plan_id,
        expected_plan_hash=expected_plan_hash,
        expected_start_date=expected_start_date,
        expected_end_date=expected_end_date,
    )
    checkpoint = _load_checkpoint(
        _validated_staging_file(
            checkpoint_path,
            staging_root=plan.staging_root,
            label="history checkpoint",
        ),
        plan=plan,
    )
    if len(checkpoint) != len(plan.segments):
        raise StockDailyTrendChannelHistoryError(
            "candidate audit requires every reviewed segment to be generated"
        )
    started_at = time.perf_counter()
    segment_reports: list[dict[str, object]] = []
    all_files: list[dict[str, object]] = []
    for segment in plan.segments:
        entry = checkpoint.get(str(segment.segment_index))
        if entry is None or not _checkpoint_segment_is_trusted(
            entry,
            plan=plan,
            segment=segment,
        ):
            raise StockDailyTrendChannelHistoryError(
                f"candidate checkpoint is not trusted for segment {segment.segment_index}"
            )
        files = _generated_files_from_checkpoint(entry)
        audit = _audit_generated_segment(
            plan=plan,
            segment=segment,
            files=files,
            duckdb_settings=duckdb_settings,
        )
        if not audit.passed:
            raise StockDailyTrendChannelHistoryError(
                "candidate segment audit failed: "
                f"segment={segment.segment_index}, dates={audit.failed_trade_dates[:20]}"
            )
        segment_reports.append(_segment_audit_dict(audit))
        all_files.extend(value.to_dict() for value in files)
    payload = {
        "schema_version": 1,
        "phase": AUDIT_PHASE,
        "plan_id": plan.plan_id,
        "plan_hash": plan.plan_hash,
        "start_date": plan.trade_dates[0],
        "end_date": plan.trade_dates[-1],
        "formula_version": FORMULA_VERSION,
        "checkpoint_sha256": _file_sha256(Path(checkpoint_path)),
        "files": all_files,
        "segment_audits": segment_reports,
        "source_partition_count": len(plan.trade_dates),
        "candidate_result_file_count": len(plan.trade_dates),
        "candidate_state_file_count": len(plan.trade_dates),
        "candidate_result_row_count": sum(
            int(value["row_count"])
            for value in all_files
            if value["asset_key"] == RESULT_ASSET_KEY
        ),
        "candidate_state_row_count": sum(
            int(value["row_count"])
            for value in all_files
            if value["asset_key"] == STATE_ASSET_KEY
        ),
        "should_stop": False,
    }
    report = {
        **payload,
        "audit_hash": _hash_payload(payload),
        "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 3),
    }
    _write_review_report(output_path, report, plan=plan)
    return report


def promote_stock_daily_trend_channel_history(
    *,
    plan: StockDailyTrendChannelHistoryPlan,
    expected_plan_id: str,
    expected_plan_hash: str,
    expected_start_date: str,
    expected_end_date: str,
    audit_report_path: Path,
    expected_audit_hash: str,
    promotion_checkpoint_path: Path,
    output_path: Path,
    dry_run: bool = True,
    confirm_write: bool = False,
    replace_file: Callable[[Path, Path], None] = os.replace,
) -> dict[str, object]:
    """Promote audited state/result pairs in date order with resumable identity checks."""

    _assert_apply_contract(
        plan=plan,
        expected_plan_id=expected_plan_id,
        expected_plan_hash=expected_plan_hash,
        expected_start_date=expected_start_date,
        expected_end_date=expected_end_date,
    )
    audit_report = _load_audit_report(
        audit_report_path,
        plan=plan,
        expected_audit_hash=expected_audit_hash,
    )
    files = tuple(_load_generated_file(value) for value in audit_report["files"])
    _validate_generated_file_scope(plan=plan, files=files)
    checkpoint_path = _validated_staging_file(
        promotion_checkpoint_path,
        staging_root=plan.staging_root,
        label="promotion checkpoint",
    )
    if dry_run:
        report = {
            "schema_version": 1,
            "phase": PROMOTE_PHASE,
            "mode": "dry-run",
            "plan_id": plan.plan_id,
            "plan_hash": plan.plan_hash,
            "audit_hash": expected_audit_hash,
            "planned_partition_count": len(plan.trade_dates),
            "planned_file_count": len(files),
            "formal_file_count": 0,
            "should_stop": False,
        }
        _write_review_report(output_path, report, plan=plan)
        return report
    if not confirm_write:
        raise StockDailyTrendChannelHistoryError(
            "history promotion requires confirm_write=True"
        )
    by_key = {(value.asset_key, value.trade_date): value for value in files}
    completed = _load_promotion_checkpoint(checkpoint_path, plan=plan)
    promoted = 0
    for trade_date in plan.trade_dates:
        for asset_key in (STATE_ASSET_KEY, RESULT_ASSET_KEY):
            value = by_key[(asset_key, trade_date)]
            _promote_generated_file(value=value, replace_file=replace_file)
        completed[trade_date] = {
            "state_sha256": by_key[(STATE_ASSET_KEY, trade_date)].sha256,
            "result_sha256": by_key[(RESULT_ASSET_KEY, trade_date)].sha256,
            "completed_at": datetime.now(UTC).isoformat(),
        }
        _write_promotion_checkpoint(checkpoint_path, plan=plan, completed=completed)
        promoted += 1
    formal_files = tuple(
        {
            "asset_key": value.asset_key,
            "trade_date": value.trade_date,
            "path": str(value.target_path),
            "row_count": value.row_count,
            "size_bytes": value.target_path.stat().st_size,
            "sha256": _file_sha256(value.target_path),
        }
        for value in files
    )
    payload = {
        "schema_version": 1,
        "phase": PROMOTE_PHASE,
        "mode": "apply",
        "plan_id": plan.plan_id,
        "plan_hash": plan.plan_hash,
        "audit_hash": expected_audit_hash,
        "start_date": plan.trade_dates[0],
        "end_date": plan.trade_dates[-1],
        "promoted_partition_count": len(completed),
        "processed_partition_count": promoted,
        "formal_file_count": len(formal_files),
        "files": list(formal_files),
        "should_stop": False,
    }
    report = {**payload, "promote_hash": _hash_payload(payload)}
    _write_review_report(output_path, report, plan=plan)
    return report


def final_audit_stock_daily_trend_channel_history(
    *,
    plan: StockDailyTrendChannelHistoryPlan,
    expected_plan_id: str,
    expected_plan_hash: str,
    expected_start_date: str,
    expected_end_date: str,
    promote_report_path: Path,
    expected_promote_hash: str,
    output_path: Path,
    duckdb_settings: DuckDBConnectionSettings = DEFAULT_DUCKDB_CONNECTION_SETTINGS,
) -> dict[str, object]:
    """Verify every promoted file and re-run bounded aggregate contract audits."""

    _assert_apply_contract(
        plan=plan,
        expected_plan_id=expected_plan_id,
        expected_plan_hash=expected_plan_hash,
        expected_start_date=expected_start_date,
        expected_end_date=expected_end_date,
    )
    promote_report = _load_promote_report(
        promote_report_path,
        plan=plan,
        expected_promote_hash=expected_promote_hash,
    )
    promoted_files = tuple(promote_report["files"])
    expected_file_count = 2 * len(plan.trade_dates)
    if len(promoted_files) != expected_file_count:
        raise StockDailyTrendChannelHistoryError(
            "promote report does not cover the complete reviewed file scope"
        )
    expected_hashes = {
        (str(value["asset_key"]), str(value["trade_date"])): str(value["sha256"])
        for value in promoted_files
    }
    segment_reports: list[dict[str, object]] = []
    for segment in plan.segments:
        result_paths = {
            trade_date: gold_stock_daily_trend_channel_path(plan.lake_root, trade_date)
            for trade_date in segment.trade_dates
        }
        state_paths = {
            trade_date: gold_stock_daily_trend_channel_state_path(
                plan.lake_root,
                trade_date,
            )
            for trade_date in segment.trade_dates
        }
        for asset_key, paths in (
            (RESULT_ASSET_KEY, result_paths),
            (STATE_ASSET_KEY, state_paths),
        ):
            for trade_date, path in paths.items():
                if not path.is_file() or _file_sha256(path) != expected_hashes.get(
                    (asset_key, trade_date)
                ):
                    raise StockDailyTrendChannelHistoryError(
                        f"formal file identity mismatch: {asset_key}:{trade_date}"
                    )
        previous_state = (
            gold_stock_daily_trend_channel_state_path(
                plan.lake_root,
                plan.trade_dates[plan.trade_dates.index(segment.start_date) - 1],
            )
            if segment.segment_index > 1
            else None
        )
        with connect_configured_duckdb(duckdb_settings) as connection:
            audit = audit_stock_daily_trend_channel_history_segment(
                connection=connection,
                trade_dates=segment.trade_dates,
                result_paths=result_paths,
                state_paths=state_paths,
                qfq_paths={
                    value.trade_date: value.path for value in segment.source_files
                },
                lifecycle_path=plan.lifecycle_path,
                previous_state_path=previous_state,
            )
        if not audit.passed:
            raise StockDailyTrendChannelHistoryError(
                "formal history audit failed: "
                f"segment={segment.segment_index}, dates={audit.failed_trade_dates[:20]}"
            )
        segment_reports.append(_segment_audit_dict(audit))
    payload = {
        "schema_version": 1,
        "phase": FINAL_AUDIT_PHASE,
        "plan_id": plan.plan_id,
        "plan_hash": plan.plan_hash,
        "promote_hash": expected_promote_hash,
        "start_date": plan.trade_dates[0],
        "end_date": plan.trade_dates[-1],
        "formal_partition_count": len(plan.trade_dates),
        "formal_result_file_count": len(plan.trade_dates),
        "formal_state_file_count": len(plan.trade_dates),
        "segment_audits": segment_reports,
        "should_stop": False,
    }
    report = {**payload, "final_audit_hash": _hash_payload(payload)}
    _write_review_report(output_path, report, plan=plan)
    return report


def validate_stock_daily_trend_channel_history_private_stage(
    *,
    plan: StockDailyTrendChannelHistoryPlan,
    expected_plan_id: str,
    expected_plan_hash: str,
    stage: str,
    output_root: Path,
    trade_day_count: int,
    stock_codes: Sequence[str] = (),
    dry_run: bool = True,
    confirm_write: bool = False,
    duckdb_settings: DuckDBConnectionSettings = DEFAULT_DUCKDB_CONNECTION_SETTINGS,
) -> dict[str, object]:
    """Run sample or benchmark candidates only under /private/tmp."""

    if stage not in {"sample", "benchmark"}:
        raise StockDailyTrendChannelHistoryError("unsupported private stage")
    if plan.plan_id != expected_plan_id or plan.plan_hash != expected_plan_hash:
        raise StockDailyTrendChannelHistoryError("private stage plan identity mismatch")
    if plan.should_stop:
        raise StockDailyTrendChannelHistoryError("private stage plan is stopped")
    if not 1 <= trade_day_count <= SEGMENT_TRADE_DAY_LIMIT:
        raise StockDailyTrendChannelHistoryError("private stage date count is invalid")
    normalized_output = Path(output_root).resolve()
    private_root = Path("/private/tmp").resolve()
    if normalized_output == private_root or not normalized_output.is_relative_to(
        private_root
    ):
        raise StockDailyTrendChannelHistoryError(
            "sample and benchmark output must be a child of /private/tmp"
        )
    selected_dates = plan.trade_dates[:trade_day_count]
    selected_codes = tuple(
        sorted(
            {str(value).strip().upper() for value in stock_codes if str(value).strip()}
        )
    )
    if stage == "sample" and not selected_codes:
        raise StockDailyTrendChannelHistoryError("sample requires explicit stock codes")
    if dry_run:
        return {
            "mode": "dry-run",
            "stage": stage,
            "trade_dates": list(selected_dates),
            "stock_codes": list(selected_codes),
            "written_file_count": 0,
        }
    if not confirm_write:
        raise StockDailyTrendChannelHistoryError(
            "private sample/benchmark write requires confirm_write=True"
        )
    normalized_output.mkdir(parents=True, exist_ok=True)
    qfq_paths = {
        value.trade_date: value.path
        for value in plan.segments[0].source_files
        if value.trade_date in set(selected_dates)
    }
    if selected_codes:
        qfq_paths = _write_private_qfq_scope(
            source_paths=qfq_paths,
            stock_codes=selected_codes,
            output_root=normalized_output,
            duckdb_settings=duckdb_settings,
        )
    segment = StockDailyTrendChannelHistorySegment(
        segment_index=1,
        trade_dates=selected_dates,
        source_files=tuple(
            StockDailyTrendChannelHistorySourceFile(
                trade_date=trade_date,
                path=qfq_paths[trade_date],
                size_bytes=qfq_paths[trade_date].stat().st_size,
                sha256=_file_sha256(qfq_paths[trade_date]),
                row_count=0,
            )
            for trade_date in selected_dates
        ),
    )
    started_at = time.perf_counter()
    generated, audit, spill, _ = _generate_history_segment(
        plan=plan,
        segment=segment,
        duckdb_settings=duckdb_settings,
        candidate_root=normalized_output / "candidates",
        qfq_paths=qfq_paths,
    )
    return {
        "mode": "apply",
        "stage": stage,
        "trade_dates": list(selected_dates),
        "stock_codes": list(selected_codes),
        "written_file_count": len(generated),
        "written_row_count": sum(value.row_count for value in generated),
        "written_bytes": sum(value.size_bytes for value in generated),
        "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 3),
        "peak_rss_mib": round(_peak_rss_mib(), 3),
        "temp_spill_bytes": spill,
        "audit_passed": audit.passed,
    }


def _discover_qfq_files(root: Path) -> tuple[tuple[str, Path], ...]:
    base = gold_stock_daily_qfq_path(root, "2000-01-01").parent.parent
    discovered: list[tuple[str, Path]] = []
    if not base.is_dir():
        return ()
    for partition_dir in sorted(base.glob("trade_date=*")):
        trade_date = partition_dir.name.removeprefix("trade_date=")
        try:
            normalized = date.fromisoformat(trade_date).isoformat()
        except ValueError as error:
            raise StockDailyTrendChannelHistoryError(
                f"invalid qfq partition directory: {partition_dir}"
            ) from error
        files = tuple(sorted(partition_dir.glob("*.parquet")))
        expected = gold_stock_daily_qfq_path(root, normalized)
        if files != (expected,):
            raise StockDailyTrendChannelHistoryError(
                f"qfq partition must contain exactly part-000.parquet: {partition_dir}"
            )
        discovered.append((normalized, expected))
    return tuple(discovered)


def _profile_qfq_history(
    *,
    connection: Any,
    discovered: Sequence[tuple[str, Path]],
    lifecycle_path: Path,
) -> tuple[dict[str, int], int, int, int, int]:
    input_values = ", ".join(
        f"({duckdb_string(path)}, DATE {duckdb_string(trade_date)})"
        for trade_date, path in discovered
    )
    path_values = ", ".join(duckdb_string(path) for _, path in discovered)
    rows = connection.execute(
        f"""
        WITH inputs(file_path, expected_trade_date) AS (VALUES {input_values}),
        qfq AS (
          SELECT
            inputs.expected_trade_date,
            CAST(rows.ts_code AS VARCHAR) AS ts_code,
            CAST(rows.trade_date AS DATE) AS trade_date
          FROM read_parquet(
            [{path_values}], filename=true, hive_partitioning=false, union_by_name=true
          ) AS rows
          JOIN inputs ON rows.filename = inputs.file_path
        ),
        lifecycle AS (
          SELECT
            CAST(ts_code AS VARCHAR) AS ts_code,
            CAST(delist_date AS DATE) AS delist_date
          FROM {read_parquet(lifecycle_path, hive_partitioning=False)}
          WHERE CAST(is_cny_stock AS BOOLEAN)
        ),
        qfq_codes AS (SELECT DISTINCT ts_code FROM qfq)
        SELECT
          count(DISTINCT qfq.ts_code),
          count(DISTINCT qfq.ts_code) FILTER (WHERE lifecycle.delist_date IS NOT NULL),
          (SELECT count(*) FROM qfq_codes codes
           WHERE NOT EXISTS (SELECT 1 FROM lifecycle WHERE lifecycle.ts_code = codes.ts_code)),
          count(*) FILTER (WHERE qfq.trade_date != qfq.expected_trade_date)
        FROM qfq
        LEFT JOIN lifecycle USING (ts_code)
        """
    ).fetchone()
    count_rows = connection.execute(
        f"""
        WITH inputs(file_path, expected_trade_date) AS (VALUES {input_values})
        SELECT strftime(inputs.expected_trade_date, '%Y-%m-%d'), count(*)
        FROM read_parquet(
          [{path_values}], filename=true, hive_partitioning=false, union_by_name=true
        ) AS rows
        JOIN inputs ON rows.filename = inputs.file_path
        GROUP BY inputs.expected_trade_date
        ORDER BY inputs.expected_trade_date
        """
    ).fetchall()
    return (
        {str(value[0]): int(value[1]) for value in count_rows},
        int(rows[0]),
        int(rows[1]),
        int(rows[2]),
        int(rows[3]),
    )


def _generate_history_segment(
    *,
    plan: StockDailyTrendChannelHistoryPlan,
    segment: StockDailyTrendChannelHistorySegment,
    duckdb_settings: DuckDBConnectionSettings,
    candidate_root: Path | None = None,
    qfq_paths: Mapping[str, Path] | None = None,
) -> tuple[
    tuple[_GeneratedFile, ...],
    StockDailyTrendChannelHistorySegmentAudit,
    int,
    float,
]:
    started_at = time.perf_counter()
    source_paths = (
        dict(qfq_paths)
        if qfq_paths is not None
        else {value.trade_date: value.path for value in segment.source_files}
    )
    run_id = f"bootstrap-{plan.plan_id}"
    result_paths = {
        trade_date: (
            candidate_root
            / RESULT_ASSET_KEY
            / f"trade_date={trade_date}"
            / "part-000.parquet"
            if candidate_root is not None
            else gold_stock_daily_trend_channel_staging_path(
                plan.staging_root,
                run_id,
                trade_date,
            )
        )
        for trade_date in segment.trade_dates
    }
    state_paths = {
        trade_date: (
            candidate_root
            / STATE_ASSET_KEY
            / f"trade_date={trade_date}"
            / "part-000.parquet"
            if candidate_root is not None
            else gold_stock_daily_trend_channel_state_staging_path(
                plan.staging_root,
                run_id,
                trade_date,
            )
        )
        for trade_date in segment.trade_dates
    }
    for path in (*result_paths.values(), *state_paths.values()):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)
    previous_state = (
        None
        if segment.segment_index == 1
        else gold_stock_daily_trend_channel_state_staging_path(
            plan.staging_root,
            run_id,
            plan.trade_dates[plan.trade_dates.index(segment.start_date) - 1],
        )
    )
    if candidate_root is not None:
        previous_state = None
    with connect_configured_duckdb(duckdb_settings) as connection:
        _create_history_relations(
            connection=connection,
            source_paths=tuple(source_paths[value] for value in segment.trade_dates),
            lifecycle_path=plan.lifecycle_path,
            trade_dates=segment.trade_dates,
            previous_state_path=previous_state,
        )
        for trade_date in segment.trade_dates:
            date_sql = duckdb_string(trade_date)
            result_sql = f"""
              SELECT
                CAST(ts_code AS VARCHAR) AS ts_code,
                CAST(trade_date AS DATE) AS trade_date,
                CAST(open AS DOUBLE) AS open,
                CAST(high AS DOUBLE) AS high,
                CAST(low AS DOUBLE) AS low,
                CAST(close AS DOUBLE) AS close,
                CAST(short_upper AS DOUBLE) AS short_upper,
                CAST(short_lower AS DOUBLE) AS short_lower,
                CAST(short_position AS VARCHAR) AS short_position,
                CAST(short_state AS VARCHAR) AS short_state,
                CAST(long_upper AS DOUBLE) AS long_upper,
                CAST(long_lower AS DOUBLE) AS long_lower,
                CAST(long_position AS VARCHAR) AS long_position,
                CAST(long_state AS VARCHAR) AS long_state,
                CAST(combined_state AS VARCHAR) AS combined_state,
                CAST(formula_version AS VARCHAR) AS formula_version
              FROM trend_history_observed
              WHERE trade_date = DATE {date_sql}
              ORDER BY ts_code
            """
            state_sql = f"""
              SELECT
                CAST(ts_code AS VARCHAR) AS ts_code,
                CAST(trade_date AS DATE) AS trade_date,
                CAST(state_source_trade_date AS DATE) AS state_source_trade_date,
                CAST(observed_on_partition AS BOOLEAN) AS observed_on_partition,
                CAST(short_upper_raw AS DOUBLE) AS short_upper_raw,
                CAST(short_lower_raw AS DOUBLE) AS short_lower_raw,
                CAST(short_state AS VARCHAR) AS short_state,
                CAST(long_upper_raw AS DOUBLE) AS long_upper_raw,
                CAST(long_lower_raw AS DOUBLE) AS long_lower_raw,
                CAST(long_state AS VARCHAR) AS long_state,
                CAST(combined_state AS VARCHAR) AS combined_state,
                CAST(formula_version AS VARCHAR) AS formula_version
              FROM trend_history_state
              WHERE trade_date = DATE {date_sql}
              ORDER BY ts_code
            """
            connection.execute(
                copy_query_to_parquet(result_sql, result_paths[trade_date])
            )
            connection.execute(
                copy_query_to_parquet(state_sql, state_paths[trade_date])
            )
        audit = audit_stock_daily_trend_channel_history_segment(
            connection=connection,
            trade_dates=segment.trade_dates,
            result_paths=result_paths,
            state_paths=state_paths,
            qfq_paths=source_paths,
            lifecycle_path=plan.lifecycle_path,
            previous_state_path=previous_state,
        )
        row_counts = _row_counts_by_path(
            connection,
            tuple(result_paths.values()) + tuple(state_paths.values()),
        )
        temp_spill_bytes = _temp_spill_bytes(connection)
    if not audit.passed:
        raise StockDailyTrendChannelHistoryError(
            "generated history segment failed shared audits: "
            f"segment={segment.segment_index}, dates={audit.failed_trade_dates[:20]}"
        )
    if temp_spill_bytes > DAILY_TEMP_SPILL_HARD_LIMIT_BYTES:
        raise StockDailyTrendChannelHistoryError(
            "history segment temp spill exceeded the reviewed hard limit"
        )
    generated = tuple(
        _generated_file(
            asset_key=asset_key,
            trade_date=trade_date,
            candidate_path=paths[trade_date],
            target_path=(
                gold_stock_daily_trend_channel_path(plan.lake_root, trade_date)
                if asset_key == RESULT_ASSET_KEY
                else gold_stock_daily_trend_channel_state_path(
                    plan.lake_root,
                    trade_date,
                )
            ),
            row_count=row_counts[paths[trade_date]],
        )
        for trade_date in segment.trade_dates
        for asset_key, paths in (
            (STATE_ASSET_KEY, state_paths),
            (RESULT_ASSET_KEY, result_paths),
        )
    )
    return generated, audit, temp_spill_bytes, (time.perf_counter() - started_at) * 1000


def _create_history_relations(
    *,
    connection: Any,
    source_paths: Sequence[Path],
    lifecycle_path: Path,
    trade_dates: Sequence[str],
    previous_state_path: Path | None,
) -> None:
    source_values = ", ".join(duckdb_string(value) for value in source_paths)
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW trend_history_source AS
        SELECT
          CAST(ts_code AS VARCHAR) AS ts_code,
          CAST(trade_date AS DATE) AS trade_date,
          CAST(open AS DOUBLE) AS open,
          CAST(high AS DOUBLE) AS high,
          CAST(low AS DOUBLE) AS low,
          CAST(close AS DOUBLE) AS close
        FROM read_parquet(
          [{source_values}], hive_partitioning=false, union_by_name=true
        )
        """
    )
    seed_relation = None
    if previous_state_path is not None:
        if not previous_state_path.is_file():
            raise StockDailyTrendChannelHistoryError(
                f"previous history state candidate is missing: {previous_state_path}"
            )
        connection.execute(
            f"""
            CREATE OR REPLACE TEMP VIEW trend_history_seed AS
            SELECT * FROM {read_parquet(previous_state_path, hive_partitioning=False)}
            """
        )
        seed_relation = "trend_history_seed"
    formula_sql = build_stock_daily_trend_channel_history_segment_sql(
        "trend_history_source",
        segment_trade_day_count=len(trade_dates),
        previous_state_relation=seed_relation,
    )
    connection.execute(
        f"CREATE OR REPLACE TEMP TABLE trend_history_observed AS {formula_sql}"
    )
    date_values = ", ".join(f"(DATE {duckdb_string(value)})" for value in trade_dates)
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE trend_history_dates AS
        SELECT CAST(col0 AS DATE) AS trade_date FROM (VALUES {date_values})
        """
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW trend_history_lifecycle AS
        SELECT
          CAST(ts_code AS VARCHAR) AS ts_code,
          CAST(is_cny_stock AS BOOLEAN) AS is_cny_stock,
          CAST(list_date AS DATE) AS list_date,
          CAST(delist_date AS DATE) AS delist_date
        FROM {read_parquet(lifecycle_path, hive_partitioning=False)}
        """
    )
    seed_sql = (
        """
        SELECT
          ts_code, state_source_trade_date, short_upper_raw, short_lower_raw,
          short_state, long_upper_raw, long_lower_raw, long_state,
          combined_state, formula_version
        FROM trend_history_seed
        """
        if previous_state_path is not None
        else """
        SELECT
          CAST(NULL AS VARCHAR), CAST(NULL AS DATE), CAST(NULL AS DOUBLE),
          CAST(NULL AS DOUBLE), CAST(NULL AS VARCHAR), CAST(NULL AS DOUBLE),
          CAST(NULL AS DOUBLE), CAST(NULL AS VARCHAR), CAST(NULL AS VARCHAR),
          CAST(NULL AS VARCHAR)
        WHERE false
        """
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE trend_history_state AS
        WITH state_events AS (
          SELECT
            ts_code, trade_date AS state_source_trade_date,
            short_upper_raw, short_lower_raw, short_state,
            long_upper_raw, long_lower_raw, long_state,
            combined_state, formula_version
          FROM trend_history_observed
          UNION ALL
          {seed_sql}
        ),
        valid_code_dates AS (
          SELECT DISTINCT lifecycle.ts_code, dates.trade_date
          FROM trend_history_dates AS dates
          JOIN trend_history_lifecycle AS lifecycle
            ON lifecycle.is_cny_stock
           AND lifecycle.list_date <= dates.trade_date
           AND (
             lifecycle.delist_date IS NULL
             OR lifecycle.delist_date > dates.trade_date
           )
        )
        SELECT
          grid.ts_code,
          grid.trade_date,
          latest.state_source_trade_date,
          latest.state_source_trade_date = grid.trade_date AS observed_on_partition,
          latest.short_upper_raw,
          latest.short_lower_raw,
          latest.short_state,
          latest.long_upper_raw,
          latest.long_lower_raw,
          latest.long_state,
          latest.combined_state,
          latest.formula_version
        FROM valid_code_dates AS grid
        JOIN LATERAL (
          SELECT event.*
          FROM state_events AS event
          WHERE event.ts_code = grid.ts_code
            AND event.state_source_trade_date <= grid.trade_date
          ORDER BY event.state_source_trade_date DESC
          LIMIT 1
        ) AS latest ON true
        ORDER BY grid.ts_code, grid.trade_date
        """
    )


def _audit_generated_segment(
    *,
    plan: StockDailyTrendChannelHistoryPlan,
    segment: StockDailyTrendChannelHistorySegment,
    files: Sequence[_GeneratedFile],
    duckdb_settings: DuckDBConnectionSettings,
) -> StockDailyTrendChannelHistorySegmentAudit:
    by_key = {(value.asset_key, value.trade_date): value for value in files}
    previous_state = (
        None
        if segment.segment_index == 1
        else gold_stock_daily_trend_channel_state_staging_path(
            plan.staging_root,
            f"bootstrap-{plan.plan_id}",
            plan.trade_dates[plan.trade_dates.index(segment.start_date) - 1],
        )
    )
    with connect_configured_duckdb(duckdb_settings) as connection:
        return audit_stock_daily_trend_channel_history_segment(
            connection=connection,
            trade_dates=segment.trade_dates,
            result_paths={
                value: by_key[(RESULT_ASSET_KEY, value)].candidate_path
                for value in segment.trade_dates
            },
            state_paths={
                value: by_key[(STATE_ASSET_KEY, value)].candidate_path
                for value in segment.trade_dates
            },
            qfq_paths={value.trade_date: value.path for value in segment.source_files},
            lifecycle_path=plan.lifecycle_path,
            previous_state_path=previous_state,
        )


def _generated_file(
    *,
    asset_key: str,
    trade_date: str,
    candidate_path: Path,
    target_path: Path,
    row_count: int,
) -> _GeneratedFile:
    return _GeneratedFile(
        asset_key=asset_key,
        trade_date=trade_date,
        candidate_path=candidate_path,
        target_path=target_path,
        row_count=row_count,
        size_bytes=candidate_path.stat().st_size,
        sha256=_file_sha256(candidate_path),
    )


def _row_counts_by_path(
    connection: Any,
    paths: Sequence[Path],
) -> dict[Path, int]:
    path_values = ", ".join(duckdb_string(value) for value in paths)
    rows = connection.execute(
        f"""
        SELECT filename, count(*)
        FROM read_parquet(
          [{path_values}], filename=true, hive_partitioning=false,
          union_by_name=true
        )
        GROUP BY filename
        """
    ).fetchall()
    row_counts = {Path(str(row[0])).resolve(): int(row[1]) for row in rows}
    expected_paths = {path.resolve() for path in paths}
    if set(row_counts) != expected_paths:
        raise StockDailyTrendChannelHistoryError(
            "generated history row-count scope differs from candidate files"
        )
    return row_counts


def _generated_files_from_checkpoint(
    entry: Mapping[str, object],
) -> tuple[_GeneratedFile, ...]:
    values = entry.get("files")
    if not isinstance(values, list):
        raise StockDailyTrendChannelHistoryError("checkpoint files are invalid")
    return tuple(_load_generated_file(value) for value in values)


def _load_generated_file(value: object) -> _GeneratedFile:
    if not isinstance(value, Mapping):
        raise StockDailyTrendChannelHistoryError("generated file record is invalid")
    return _GeneratedFile(
        asset_key=str(value.get("asset_key", "")),
        trade_date=_normalize_trade_date(str(value.get("trade_date", ""))),
        candidate_path=Path(str(value.get("candidate_path", ""))).resolve(),
        target_path=Path(str(value.get("target_path", ""))).resolve(),
        row_count=int(value.get("row_count", 0)),
        size_bytes=int(value.get("size_bytes", 0)),
        sha256=str(value.get("sha256", "")),
    )


def _checkpoint_segment_is_trusted(
    entry: Mapping[str, object],
    *,
    plan: StockDailyTrendChannelHistoryPlan,
    segment: StockDailyTrendChannelHistorySegment,
) -> bool:
    try:
        files = _generated_files_from_checkpoint(entry)
        _validate_generated_segment_scope(plan=plan, segment=segment, files=files)
    except (OSError, ValueError, StockDailyTrendChannelHistoryError):
        return False
    return all(
        value.candidate_path.is_file()
        and value.candidate_path.stat().st_size == value.size_bytes
        and _file_sha256(value.candidate_path) == value.sha256
        for value in files
    )


def _validate_generated_segment_scope(
    *,
    plan: StockDailyTrendChannelHistoryPlan,
    segment: StockDailyTrendChannelHistorySegment,
    files: Sequence[_GeneratedFile],
) -> None:
    expected = {
        (asset_key, trade_date)
        for trade_date in segment.trade_dates
        for asset_key in (RESULT_ASSET_KEY, STATE_ASSET_KEY)
    }
    observed = {(value.asset_key, value.trade_date) for value in files}
    if observed != expected or len(files) != len(expected):
        raise StockDailyTrendChannelHistoryError(
            "generated segment file scope differs from the reviewed plan"
        )
    run_id = f"bootstrap-{plan.plan_id}"
    for value in files:
        expected_candidate = (
            gold_stock_daily_trend_channel_staging_path(
                plan.staging_root,
                run_id,
                value.trade_date,
            )
            if value.asset_key == RESULT_ASSET_KEY
            else gold_stock_daily_trend_channel_state_staging_path(
                plan.staging_root,
                run_id,
                value.trade_date,
            )
        )
        expected_target = (
            gold_stock_daily_trend_channel_path(plan.lake_root, value.trade_date)
            if value.asset_key == RESULT_ASSET_KEY
            else gold_stock_daily_trend_channel_state_path(
                plan.lake_root,
                value.trade_date,
            )
        )
        if (
            value.candidate_path != expected_candidate
            or value.target_path != expected_target
        ):
            raise StockDailyTrendChannelHistoryError(
                "generated file path escaped the reviewed scope"
            )


def _validate_generated_file_scope(
    *,
    plan: StockDailyTrendChannelHistoryPlan,
    files: Sequence[_GeneratedFile],
) -> None:
    expected = {
        (asset_key, trade_date)
        for trade_date in plan.trade_dates
        for asset_key in (RESULT_ASSET_KEY, STATE_ASSET_KEY)
    }
    observed = {(value.asset_key, value.trade_date) for value in files}
    if observed != expected or len(files) != len(expected):
        raise StockDailyTrendChannelHistoryError(
            "generated file scope differs from the complete reviewed plan"
        )
    for segment in plan.segments:
        _validate_generated_segment_scope(
            plan=plan,
            segment=segment,
            files=tuple(
                value for value in files if value.trade_date in set(segment.trade_dates)
            ),
        )


def _promote_generated_file(
    *,
    value: _GeneratedFile,
    replace_file: Callable[[Path, Path], None],
) -> None:
    if value.target_path.is_file():
        if _file_sha256(value.target_path) != value.sha256:
            raise StockDailyTrendChannelHistoryError(
                f"formal target conflicts with reviewed candidate: {value.target_path}"
            )
        return
    if (
        not value.candidate_path.is_file()
        or _file_sha256(value.candidate_path) != value.sha256
    ):
        raise StockDailyTrendChannelHistoryError(
            f"reviewed candidate is missing or changed: {value.candidate_path}"
        )
    value.target_path.parent.mkdir(parents=True, exist_ok=True)
    if value.candidate_path.stat().st_dev != value.target_path.parent.stat().st_dev:
        raise StockDailyTrendChannelHistoryError(
            "candidate and formal target are not on the same filesystem"
        )
    replace_file(value.candidate_path, value.target_path)
    if _file_sha256(value.target_path) != value.sha256:
        raise StockDailyTrendChannelHistoryError(
            f"promoted file identity changed: {value.target_path}"
        )


def _load_audit_report(
    path: Path,
    *,
    plan: StockDailyTrendChannelHistoryPlan,
    expected_audit_hash: str,
) -> Mapping[str, Any]:
    report = _load_json(path, label="trend-channel candidate audit")
    payload = {
        key: value
        for key, value in report.items()
        if key not in {"audit_hash", "elapsed_ms"}
    }
    if (
        report.get("phase") != AUDIT_PHASE
        or report.get("plan_id") != plan.plan_id
        or report.get("plan_hash") != plan.plan_hash
        or report.get("should_stop") is not False
        or report.get("audit_hash") != expected_audit_hash
        or _hash_payload(payload) != expected_audit_hash
    ):
        raise StockDailyTrendChannelHistoryError(
            "candidate audit report is not trusted"
        )
    return report


def _load_promote_report(
    path: Path,
    *,
    plan: StockDailyTrendChannelHistoryPlan,
    expected_promote_hash: str,
) -> Mapping[str, Any]:
    report = _load_json(path, label="trend-channel promotion")
    payload = {key: value for key, value in report.items() if key != "promote_hash"}
    if (
        report.get("phase") != PROMOTE_PHASE
        or report.get("mode") != "apply"
        or report.get("plan_id") != plan.plan_id
        or report.get("plan_hash") != plan.plan_hash
        or report.get("should_stop") is not False
        or report.get("promote_hash") != expected_promote_hash
        or _hash_payload(payload) != expected_promote_hash
    ):
        raise StockDailyTrendChannelHistoryError("promotion report is not trusted")
    return report


def _load_checkpoint(
    path: Path,
    *,
    plan: StockDailyTrendChannelHistoryPlan,
) -> dict[str, Mapping[str, object]]:
    if not path.exists():
        return {}
    payload = _load_json(path, label="trend-channel history checkpoint")
    if (
        payload.get("schema_version") != 1
        or payload.get("phase") != CHECKPOINT_PHASE
        or payload.get("plan_id") != plan.plan_id
        or payload.get("plan_hash") != plan.plan_hash
    ):
        raise StockDailyTrendChannelHistoryError("history checkpoint is not trusted")
    completed = payload.get("completed_segments")
    if not isinstance(completed, Mapping):
        raise StockDailyTrendChannelHistoryError("history checkpoint scope is invalid")
    valid = {str(value.segment_index) for value in plan.segments}
    if not set(completed).issubset(valid):
        raise StockDailyTrendChannelHistoryError(
            "history checkpoint contains an unreviewed segment"
        )
    return {
        str(key): value
        for key, value in completed.items()
        if isinstance(value, Mapping)
    }


def _write_checkpoint(
    path: Path,
    *,
    plan: StockDailyTrendChannelHistoryPlan,
    completed: Mapping[str, Mapping[str, object]],
) -> None:
    _write_json_atomic(
        path,
        {
            "schema_version": 1,
            "phase": CHECKPOINT_PHASE,
            "plan_id": plan.plan_id,
            "plan_hash": plan.plan_hash,
            "completed_segments": completed,
            "updated_at": datetime.now(UTC).isoformat(),
        },
    )


def _load_promotion_checkpoint(
    path: Path,
    *,
    plan: StockDailyTrendChannelHistoryPlan,
) -> dict[str, Mapping[str, object]]:
    if not path.exists():
        return {}
    payload = _load_json(path, label="trend-channel promotion checkpoint")
    if (
        payload.get("plan_id") != plan.plan_id
        or payload.get("plan_hash") != plan.plan_hash
    ):
        raise StockDailyTrendChannelHistoryError("promotion checkpoint is not trusted")
    completed = payload.get("completed_partitions")
    if not isinstance(completed, Mapping) or not set(completed).issubset(
        set(plan.trade_dates)
    ):
        raise StockDailyTrendChannelHistoryError(
            "promotion checkpoint scope is invalid"
        )
    return {
        str(key): value
        for key, value in completed.items()
        if isinstance(value, Mapping)
    }


def _write_promotion_checkpoint(
    path: Path,
    *,
    plan: StockDailyTrendChannelHistoryPlan,
    completed: Mapping[str, Mapping[str, object]],
) -> None:
    _write_json_atomic(
        path,
        {
            "schema_version": 1,
            "phase": PROMOTE_PHASE,
            "plan_id": plan.plan_id,
            "plan_hash": plan.plan_hash,
            "completed_partitions": completed,
            "updated_at": datetime.now(UTC).isoformat(),
        },
    )


def _write_private_qfq_scope(
    *,
    source_paths: Mapping[str, Path],
    stock_codes: Sequence[str],
    output_root: Path,
    duckdb_settings: DuckDBConnectionSettings,
) -> dict[str, Path]:
    code_values = ", ".join(f"({duckdb_string(value)})" for value in stock_codes)
    output_paths: dict[str, Path] = {}
    with connect_configured_duckdb(duckdb_settings) as connection:
        connection.execute(
            f"CREATE TEMP TABLE private_codes AS SELECT col0 AS ts_code FROM (VALUES {code_values})"
        )
        for trade_date, source_path in source_paths.items():
            output = (
                output_root / "qfq" / f"trade_date={trade_date}" / "part-000.parquet"
            )
            output.parent.mkdir(parents=True, exist_ok=True)
            connection.execute(
                copy_query_to_parquet(
                    f"""
                    SELECT source.*
                    FROM {read_parquet(source_path, hive_partitioning=False)} AS source
                    JOIN private_codes USING (ts_code)
                    ORDER BY ts_code
                    """,
                    output,
                )
            )
            output_paths[trade_date] = output
    return output_paths


def _validate_plan_structure(plan: StockDailyTrendChannelHistoryPlan) -> None:
    if not plan.plan_id or not plan.segments:
        raise StockDailyTrendChannelHistoryError("history plan scope is empty")
    dates = plan.trade_dates
    if dates != tuple(sorted(set(dates))):
        raise StockDailyTrendChannelHistoryError(
            "history plan dates must be sorted and unique"
        )
    if len(dates) > BOOTSTRAP_HISTORY_PARTITION_LIMIT:
        raise StockDailyTrendChannelHistoryError("history plan date scope is too large")
    for expected_index, segment in enumerate(plan.segments, start=1):
        if segment.segment_index != expected_index:
            raise StockDailyTrendChannelHistoryError(
                "history segment indexes must be contiguous"
            )
        if not 1 <= len(segment.trade_dates) <= SEGMENT_TRADE_DAY_LIMIT:
            raise StockDailyTrendChannelHistoryError(
                "history segment date count is outside the reviewed bound"
            )


def _assert_apply_contract(
    *,
    plan: StockDailyTrendChannelHistoryPlan,
    expected_plan_id: str,
    expected_plan_hash: str,
    expected_start_date: str,
    expected_end_date: str,
) -> None:
    if plan.should_stop:
        raise StockDailyTrendChannelHistoryError(
            "history plan is stopped: " + ", ".join(plan.stop_reasons)
        )
    if plan.plan_id != expected_plan_id or plan.plan_hash != expected_plan_hash:
        raise StockDailyTrendChannelHistoryError("history plan identity mismatch")
    if (
        not plan.trade_dates
        or _normalize_trade_date(expected_start_date) != plan.trade_dates[0]
        or _normalize_trade_date(expected_end_date) != plan.trade_dates[-1]
    ):
        raise StockDailyTrendChannelHistoryError(
            "history apply range must equal the complete reviewed qfq scope"
        )


def _validate_lifecycle_identity(plan: StockDailyTrendChannelHistoryPlan) -> None:
    if (
        not plan.lifecycle_path.is_file()
        or _file_sha256(plan.lifecycle_path) != plan.lifecycle_sha256
    ):
        raise StockDailyTrendChannelHistoryError(
            "stock lifecycle changed after history plan review"
        )


def _validate_segment_sources(segment: StockDailyTrendChannelHistorySegment) -> None:
    for value in segment.source_files:
        if (
            not value.path.is_file()
            or value.path.stat().st_size != value.size_bytes
            or _file_sha256(value.path) != value.sha256
        ):
            raise StockDailyTrendChannelHistoryError(
                f"qfq source changed after plan review: {value.path}"
            )


def _assert_current_disk_capacity(plan: StockDailyTrendChannelHistoryPlan) -> None:
    estimated = int(plan.report.get("estimated_candidate_bytes", 0))
    required = 2 * estimated + DAILY_TEMP_SPILL_HARD_LIMIT_BYTES
    if shutil.disk_usage(plan.staging_root).free < required:
        raise StockDailyTrendChannelHistoryError(
            "staging space no longer satisfies the reviewed bootstrap gate"
        )
    if shutil.disk_usage(plan.lake_root).free < estimated:
        raise StockDailyTrendChannelHistoryError(
            "formal Lake space no longer satisfies the reviewed bootstrap gate"
        )


def _validated_staging_file(path: Path, *, staging_root: Path, label: str) -> Path:
    normalized = Path(path).resolve()
    staging = Path(staging_root).resolve()
    if normalized == staging or not normalized.is_relative_to(staging):
        raise StockDailyTrendChannelHistoryError(
            f"{label} must be a file below the staging root"
        )
    return normalized


def _assert_report_directory(
    output_dir: Path,
    *,
    lake_root: Path,
    staging_root: Path,
) -> None:
    if output_dir == lake_root or output_dir.is_relative_to(lake_root):
        raise StockDailyTrendChannelHistoryError(
            "review reports must not be written under the formal Lake root"
        )
    if output_dir == staging_root or output_dir.is_relative_to(staging_root):
        raise StockDailyTrendChannelHistoryError(
            "review reports must remain separate from candidate staging"
        )


def _write_review_report(
    path: Path,
    payload: Mapping[str, object],
    *,
    plan: StockDailyTrendChannelHistoryPlan,
) -> None:
    normalized = Path(path).resolve()
    _assert_report_directory(
        normalized.parent,
        lake_root=plan.lake_root,
        staging_root=plan.staging_root,
    )
    _write_json_atomic(normalized, payload)


def _load_segment(value: object) -> StockDailyTrendChannelHistorySegment:
    if not isinstance(value, Mapping):
        raise StockDailyTrendChannelHistoryError("history segment is invalid")
    files = tuple(_load_source_file(item) for item in value.get("source_files", ()))
    trade_dates = tuple(str(item) for item in value.get("trade_dates", ()))
    if trade_dates != tuple(item.trade_date for item in files):
        raise StockDailyTrendChannelHistoryError(
            "history segment file/date scope is inconsistent"
        )
    return StockDailyTrendChannelHistorySegment(
        segment_index=int(value.get("segment_index", 0)),
        trade_dates=trade_dates,
        source_files=files,
    )


def _load_source_file(value: object) -> StockDailyTrendChannelHistorySourceFile:
    if not isinstance(value, Mapping):
        raise StockDailyTrendChannelHistoryError("history source file is invalid")
    return StockDailyTrendChannelHistorySourceFile(
        trade_date=_normalize_trade_date(str(value.get("trade_date", ""))),
        path=Path(str(value.get("path", ""))).resolve(),
        size_bytes=int(value.get("size_bytes", 0)),
        sha256=str(value.get("sha256", "")),
        row_count=int(value.get("row_count", 0)),
    )


def _normalize_trade_date(value: str) -> str:
    normalized = str(value).strip()
    try:
        parsed = date.fromisoformat(normalized)
    except ValueError as error:
        raise StockDailyTrendChannelHistoryError(
            f"invalid ISO trade date: {value!r}"
        ) from error
    if parsed.isoformat() != normalized:
        raise StockDailyTrendChannelHistoryError(f"invalid ISO trade date: {value!r}")
    return normalized


def _segment_audit_dict(
    audit: StockDailyTrendChannelHistorySegmentAudit,
) -> dict[str, object]:
    return {
        "start_date": audit.trade_dates[0],
        "end_date": audit.trade_dates[-1],
        "trade_date_count": len(audit.trade_dates),
        "passed": audit.passed,
        "failed_trade_dates": list(audit.failed_trade_dates),
        "elapsed_ms": audit.elapsed_ms,
        "scanned_file_count": audit.scanned_file_count,
        "sql_count": audit.sql_count,
        "slowest_query_ms": audit.slowest_query_ms,
    }


def _temp_spill_bytes(connection: Any) -> int:
    return int(
        connection.execute(
            "SELECT coalesce(sum(size), 0) FROM duckdb_temporary_files()"
        ).fetchone()[0]
    )


def _peak_rss_mib() -> float:
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if os.uname().sysname == "Darwin":
        return value / (1024 * 1024)
    return value / 1024


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _hash_payload(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_json(path: Path, *, label: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StockDailyTrendChannelHistoryError(
            f"{label} is unreadable: {path}"
        ) from error
    if not isinstance(payload, Mapping):
        raise StockDailyTrendChannelHistoryError(f"{label} must be an object")
    return payload


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(f".{path.name}.pending-{uuid.uuid4().hex}")
    pending.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(pending, path)


__all__ = [
    "StockDailyTrendChannelHistoryError",
    "StockDailyTrendChannelHistoryPlan",
    "audit_stock_daily_trend_channel_history_candidates",
    "final_audit_stock_daily_trend_channel_history",
    "generate_stock_daily_trend_channel_history",
    "load_stock_daily_trend_channel_history_plan",
    "plan_stock_daily_trend_channel_history",
    "promote_stock_daily_trend_channel_history",
    "validate_stock_daily_trend_channel_history_private_stage",
]
