"""Frozen-plan Direct Lake Bootstrap for ETF minute Raw partitions."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import uuid
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any
from zoneinfo import ZoneInfo

import dagster as dg
import duckdb as duckdb_module
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs.asset_guards.etf_basic_readiness import (
    select_latest_etf_basic_snapshot_reference,
)
from orchestrator.defs.asset_guards.etf_mins_lake_readiness import (
    EtfMinsRawCandidateValidation,
    evaluate_etf_mins_raw_candidate,
)
from orchestrator.defs.assets.etf_mins import (
    RAW_ETF_MINS_ASSETS,
    SILVER_ETF_MINS_ASSETS,
    build_etf_mins_silver_copy_sql,
    create_etf_mins_frozen_basic_relations,
    etf_mins_relations_are_semantically_equal,
    revalidate_etf_mins_basic_reference,
)
from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.partitions import cn_a_etf_mins_trade_days
from orchestrator.defs.paths import (
    etf_mins_staging_path,
    raw_etf_basic_snapshot_path,
    raw_etf_mins_path,
    silver_etf_basic_snapshot_path,
    silver_etf_mins_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.prod_db.etf_mins import (
    ProdEtfMinsFrequencyCoverage,
    build_prod_etf_mins_duckdb_attach_sql,
    build_prod_etf_mins_duckdb_source_sql,
    load_prod_etf_mins_code_coverage,
    validate_prod_etf_mins_duckdb_contract,
    validate_prod_etf_mins_select_contract,
)
from orchestrator.defs.resources import DuckDBResource, ProdPostgresResource
from orchestrator.defs.run_contracts.asset_column_schemas import RAW_ETF_MINS_SCHEMA
from orchestrator.defs.run_contracts.etf_basic import (
    EtfBasicSilverSnapshotReference,
    build_etf_basic_silver_snapshot_reference,
)
from orchestrator.defs.run_contracts.etf_mins import (
    ETF_MINS_BOOTSTRAP_BATCH_TRADE_DAY_LIMIT,
    ETF_MINS_BOOTSTRAP_DISK_SAFETY_MULTIPLIER,
    ETF_MINS_BOOTSTRAP_MAX_TARGET_FILES,
    ETF_MINS_HISTORICAL_PROTECTION_CUTOFF,
    ETF_MINS_RAW_OBSERVATION_REASON_CODES,
    ETF_MINS_SENSOR_WINDOW_LIMIT,
    ETF_MINS_SOURCE_COLUMNS,
    ETF_MINS_SOURCE_FREQS,
    EtfMinsRequestableTarget,
    get_etf_mins_raw_decision_policy,
    normalize_etf_mins_source_freq,
    normalize_etf_mins_trade_date,
    raw_etf_mins_check_names,
    silver_etf_mins_check_names,
)
from orchestrator.defs.run_contracts.metadata import (
    CheckScope,
    build_check_metadata,
    build_materialization_metadata,
)

ETF_MINS_BOOTSTRAP_SCHEMA_VERSION = 1
ETF_MINS_BOOTSTRAP_KIND = "etf_mins_direct_lake_bootstrap"
ETF_MINS_BOOTSTRAP_PROTECTION_NOT_APPLICABLE = "not_applicable"
ETF_MINS_BOOTSTRAP_PROTECTION_2026 = "protect_trade_date_gte_2026_01_01"
ETF_MINS_BOOTSTRAP_TARGET_STATES = (
    "missing",
    "present_structurally_valid_uncompared",
    "present_invalid",
)

_ESTIMATE_BASIS = (
    "P0_2026-08-30:20_trade_days_all_freqs=10460000_rows;"
    "max_1min_batch=7854190_rows;single_day_1min=396927_rows/4.44MiB"
)
_ESTIMATED_SOURCE_ROWS_PER_TRADE_DATE = 523_000
_ESTIMATED_PARQUET_BYTES_PER_ROW = 12
_RAW_SCHEMA = tuple((column.name, column.type) for column in RAW_ETF_MINS_SCHEMA)
_RAW_COLUMNS_SQL = ", ".join(ETF_MINS_SOURCE_COLUMNS)
_BASIC_ALL_RELATION = "etf_basic_all"
_REQUESTABLE_RELATION = "etf_mins_requestable_targets"
_SOURCE_BATCH_RELATION = "etf_mins_source_batch"
_SOURCE_DATE_RELATION = "etf_mins_source_date"
_CANDIDATE_RELATION = "etf_mins_candidate"
_EXISTING_RELATION = "etf_mins_existing_target"
_SILVER_WORK_MANIFEST_FILENAME = "silver_work_manifest.parquet"
_FINALIZED_SILVER_MANIFEST_FILENAME = "finalized_silver_manifest.parquet"
_PHYSICAL_FINAL_REPORT_FILENAME = "physical_final_report.json"
_SILVER_CHECKPOINT_FILENAME = "silver_checkpoint.json"
_ETF_MINS_EVENT_CHECK_WINDOW = 20
_ETF_MINS_MAX_CHECK_EVENT_COUNT = 500
_ETF_MINS_PARTITION_SET_NAME = cn_a_etf_mins_trade_days.name

_SILVER_WORK_MANIFEST_COLUMNS = (
    "operation_id",
    "plan_fingerprint",
    "source_freq",
    "trade_date",
    "formal_raw_relative_path",
    "formal_raw_sha256",
    "formal_raw_row_count",
    "formal_silver_relative_path",
    "decision",
    "decision_reason_codes_json",
    "approved_policy_version",
    "approved_policy_hash",
    "initial_silver_target_state",
)
_FINALIZED_SILVER_MANIFEST_COLUMNS = (
    "operation_id",
    "plan_fingerprint",
    "source_freq",
    "trade_date",
    "formal_raw_relative_path",
    "formal_raw_sha256",
    "formal_raw_row_count",
    "formal_silver_relative_path",
    "formal_silver_sha256",
    "formal_silver_size_bytes",
    "formal_silver_row_count",
    "disposition",
    "decision",
    "decision_reason_codes_json",
    "approved_policy_version",
    "approved_policy_hash",
)


class EtfMinsBootstrapError(RuntimeError):
    """Raised when a frozen ETF minute Bootstrap contract cannot be closed."""


@dataclass(frozen=True, slots=True)
class EtfMinsBootstrapPlan:
    operation_id: str
    schema_version: int
    created_at: str
    requested_start_date: str
    requested_end_date: str
    execution_watermark_date: str
    execution_watermark_coverage_fingerprint: str
    expected_trade_dates: tuple[str, ...]
    expected_trade_dates_hash: str
    trimmed_trade_dates: tuple[str, ...]
    frequencies: tuple[str, ...]
    frequencies_hash: str
    plan_coverage_query_count: int
    raw_detail_query_count: int
    expected_remote_query_count: int
    basic_raw_snapshot_hash: str
    basic_silver_content_hash: str
    basic_raw_observed_at: str
    basic_silver_observed_at: str
    eligibility_as_of: str
    requestable_code_count: int
    requestable_code_hash: str
    target_file_count: int
    estimated_source_rows: int
    estimate_basis: str
    estimated_staging_bytes: int
    estimated_final_increment_bytes: int
    free_bytes: int
    required_free_bytes: int
    preexisting_target_state_summary: Mapping[str, int]
    preexisting_target_manifest: tuple[Mapping[str, object], ...]
    preexisting_target_manifest_hash: str
    preexisting_silver_state_summary: Mapping[str, int]
    historical_protection_mode: str
    protected_file_manifest: tuple[Mapping[str, object], ...]
    protected_file_manifest_hash: str | None
    should_stop: bool
    stop_reasons: tuple[str, ...]
    plan_fingerprint: str

    def to_dict(self) -> dict[str, object]:
        return {
            "bootstrap_kind": ETF_MINS_BOOTSTRAP_KIND,
            "operation_id": self.operation_id,
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "requested_start_date": self.requested_start_date,
            "requested_end_date": self.requested_end_date,
            "execution_watermark_date": self.execution_watermark_date,
            "execution_watermark_coverage_fingerprint": (
                self.execution_watermark_coverage_fingerprint
            ),
            "expected_trade_dates": list(self.expected_trade_dates),
            "expected_trade_dates_hash": self.expected_trade_dates_hash,
            "trimmed_trade_dates": list(self.trimmed_trade_dates),
            "frequencies": list(self.frequencies),
            "frequencies_hash": self.frequencies_hash,
            "plan_coverage_query_count": self.plan_coverage_query_count,
            "raw_detail_query_count": self.raw_detail_query_count,
            "expected_remote_query_count": self.expected_remote_query_count,
            "basic_raw_snapshot_hash": self.basic_raw_snapshot_hash,
            "basic_silver_content_hash": self.basic_silver_content_hash,
            "basic_raw_observed_at": self.basic_raw_observed_at,
            "basic_silver_observed_at": self.basic_silver_observed_at,
            "eligibility_as_of": self.eligibility_as_of,
            "requestable_code_count": self.requestable_code_count,
            "requestable_code_hash": self.requestable_code_hash,
            "target_file_count": self.target_file_count,
            "estimated_source_rows": self.estimated_source_rows,
            "estimate_basis": self.estimate_basis,
            "estimated_staging_bytes": self.estimated_staging_bytes,
            "estimated_final_increment_bytes": self.estimated_final_increment_bytes,
            "free_bytes": self.free_bytes,
            "required_free_bytes": self.required_free_bytes,
            "preexisting_target_state_summary": dict(
                self.preexisting_target_state_summary
            ),
            "preexisting_target_manifest": [
                dict(row) for row in self.preexisting_target_manifest
            ],
            "preexisting_target_manifest_hash": (self.preexisting_target_manifest_hash),
            "preexisting_silver_state_summary": dict(
                self.preexisting_silver_state_summary
            ),
            "historical_protection_mode": self.historical_protection_mode,
            "protected_file_manifest": [
                dict(row) for row in self.protected_file_manifest
            ],
            "protected_file_manifest_hash": self.protected_file_manifest_hash,
            "should_stop": self.should_stop,
            "stop_reasons": list(self.stop_reasons),
            "plan_fingerprint": self.plan_fingerprint,
        }


@dataclass(frozen=True, slots=True)
class EtfMinsBootstrapRawApplyReport:
    operation_id: str
    plan_fingerprint: str
    plan_path: Path
    checkpoint_path: Path
    finalized_raw_manifest_path: Path
    finalized_raw_manifest_hash: str
    raw_final_report_path: Path
    source_row_count: int
    staging_row_count: int
    formal_raw_row_count: int
    added_file_count: int
    reused_file_count: int
    zero_row_file_count: int
    actual_remote_query_count: int
    temporary_space_peak_bytes: int
    final_space_increment_bytes: int
    checkpoint_hash: str
    report_hash: str


@dataclass(frozen=True, slots=True)
class EtfMinsBootstrapRawEvidence:
    """Validated local evidence consumed by post-Raw Bootstrap stages."""

    plan: EtfMinsBootstrapPlan
    raw_apply_report: EtfMinsBootstrapRawApplyReport
    basic_reference: EtfBasicSilverSnapshotReference
    finalized_raw_manifest: tuple[Mapping[str, object], ...]


@dataclass(frozen=True, slots=True)
class EtfMinsBootstrapSilverApplyReport:
    operation_id: str
    plan_fingerprint: str
    raw_final_report_hash: str
    raw_observation_summary_hash: str
    raw_decision_summary_hash: str
    finalized_raw_manifest_hash: str
    silver_work_manifest_path: Path
    silver_work_manifest_hash: str
    finalized_silver_manifest_path: Path
    finalized_silver_manifest_hash: str
    checkpoint_path: Path
    final_report_path: Path
    raw_file_count: int
    raw_row_count: int
    silver_file_count: int
    silver_row_count: int
    added_file_count: int
    reused_file_count: int
    blocked_partition_count: int
    warn_partition_count: int
    checkpoint_hash: str
    report_hash: str


@dataclass(frozen=True, slots=True)
class EtfMinsBootstrapPartitionReport:
    mode: str
    operation_id: str
    plan_fingerprint: str
    physical_final_report_hash: str
    partition_set_name: str
    planned_partition_count: int
    existing_planned_partition_count: int
    missing_partition_count: int
    added_partition_count: int
    planned_trade_dates: tuple[str, ...]
    missing_trade_dates: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "operation_id": self.operation_id,
            "plan_fingerprint": self.plan_fingerprint,
            "physical_final_report_hash": self.physical_final_report_hash,
            "partition_set_name": self.partition_set_name,
            "planned_partition_count": self.planned_partition_count,
            "existing_planned_partition_count": (self.existing_planned_partition_count),
            "missing_partition_count": self.missing_partition_count,
            "added_partition_count": self.added_partition_count,
            "planned_trade_dates": list(self.planned_trade_dates),
            "missing_trade_dates": list(self.missing_trade_dates),
        }


@dataclass(frozen=True, slots=True)
class EtfMinsBootstrapEventReport:
    mode: str
    operation_id: str
    plan_fingerprint: str
    physical_final_report_hash: str
    partition_set_name: str
    registered_partition_count: int
    raw_materialization_count: int
    silver_materialization_count: int
    existing_equivalent_materialization_count: int
    pending_materialization_count: int
    reported_materialization_count: int
    recent_check_trade_dates: tuple[str, ...]
    planned_check_event_count: int
    existing_equivalent_check_event_count: int
    pending_check_event_count: int
    reported_check_event_count: int
    materialization_query_count: int
    check_history_query_count: int
    verified_file_count: int
    verified_file_bytes: int
    sample_trade_dates: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "operation_id": self.operation_id,
            "plan_fingerprint": self.plan_fingerprint,
            "physical_final_report_hash": self.physical_final_report_hash,
            "partition_set_name": self.partition_set_name,
            "registered_partition_count": self.registered_partition_count,
            "raw_materialization_count": self.raw_materialization_count,
            "silver_materialization_count": self.silver_materialization_count,
            "existing_equivalent_materialization_count": (
                self.existing_equivalent_materialization_count
            ),
            "pending_materialization_count": self.pending_materialization_count,
            "reported_materialization_count": self.reported_materialization_count,
            "recent_check_trade_dates": list(self.recent_check_trade_dates),
            "planned_check_event_count": self.planned_check_event_count,
            "existing_equivalent_check_event_count": (
                self.existing_equivalent_check_event_count
            ),
            "pending_check_event_count": self.pending_check_event_count,
            "reported_check_event_count": self.reported_check_event_count,
            "materialization_query_count": self.materialization_query_count,
            "check_history_query_count": self.check_history_query_count,
            "verified_file_count": self.verified_file_count,
            "verified_file_bytes": self.verified_file_bytes,
            "sample_trade_dates": list(self.sample_trade_dates),
        }


@dataclass(frozen=True, slots=True)
class _EtfMinsBootstrapPhysicalEvidence:
    report: EtfMinsBootstrapSilverApplyReport
    report_payload: Mapping[str, object]
    raw_evidence: EtfMinsBootstrapRawEvidence
    decision_rows: tuple[Mapping[str, object], ...]
    finalized_silver_rows: tuple[Mapping[str, object], ...]
    verified_file_count: int
    verified_file_bytes: int


@dataclass(frozen=True, slots=True)
class _EtfMinsMaterializationEventSpec:
    asset_key: dg.AssetKey
    partition_key: str
    source_freq: str
    layer: str
    metadata: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class _EtfMinsCheckEventSpec:
    asset_key: dg.AssetKey
    partition_key: str
    check_name: str
    passed: bool
    metadata: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class _EtfMinsBootstrapEventContext:
    evidence: _EtfMinsBootstrapPhysicalEvidence
    planned_trade_dates: tuple[str, ...]
    registered_trade_dates: tuple[str, ...]
    materialization_specs: tuple[_EtfMinsMaterializationEventSpec, ...]
    check_specs: tuple[_EtfMinsCheckEventSpec, ...]
    materializations_by_key: Mapping[tuple[str, str], object]
    checks_by_key: Mapping[tuple[str, str, str], object]
    pending_materialization_specs: tuple[_EtfMinsMaterializationEventSpec, ...]
    pending_check_specs: tuple[_EtfMinsCheckEventSpec, ...]
    materialization_query_count: int
    check_history_query_count: int


def compute_etf_mins_bootstrap_payload_hash(
    payload: Mapping[str, object],
    *,
    self_hash_field: str | None = None,
) -> str:
    """Hash a complete logical JSON payload with stable key ordering."""

    normalized = dict(payload)
    if self_hash_field is not None:
        normalized.pop(self_hash_field, None)
    encoded = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def compute_etf_mins_bootstrap_manifest_hash(
    rows: Iterable[Mapping[str, object]],
    *,
    key_fields: Sequence[str],
) -> str:
    """Hash all logical manifest fields after sorting by the contract key."""

    normalized_rows = tuple(dict(row) for row in rows)
    try:
        ordered_rows = sorted(
            normalized_rows,
            key=lambda row: tuple(str(row[field]) for field in key_fields),
        )
    except KeyError as error:
        raise EtfMinsBootstrapError(
            f"etf_mins_manifest_key_missing: {error.args[0]}."
        ) from error
    return compute_etf_mins_bootstrap_payload_hash({"rows": ordered_rows})


def operation_root_for_etf_mins_bootstrap(
    *,
    staging_root: Path,
    operation_id: str,
) -> Path:
    normalized_operation_id = _normalize_operation_id(operation_id)
    return staging_root / "etf_mins" / f"operation_id={normalized_operation_id}"


def validate_etf_mins_bootstrap_operation_path(
    path: Path,
    *,
    staging_root: Path,
    expected_operation_id: str | None = None,
) -> tuple[Path, str]:
    """Require an absolute path inside one explicit ETF operation directory."""

    if not path.is_absolute():
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_path_not_absolute: an explicit absolute path is required."
        )
    base = (staging_root / "etf_mins").resolve(strict=False)
    resolved = path.resolve(strict=False)
    if not resolved.is_relative_to(base):
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_path_outside_staging: path must be under the ETF "
            "operation staging root."
        )
    relative_parts = resolved.relative_to(base).parts
    if len(relative_parts) < 2 or not relative_parts[0].startswith("operation_id="):
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_operation_boundary_missing: path must include one "
            "operation_id=<operation_id> directory and a file beneath it."
        )
    operation_id = _normalize_operation_id(relative_parts[0].split("=", 1)[1])
    operation_root = operation_root_for_etf_mins_bootstrap(
        staging_root=staging_root,
        operation_id=operation_id,
    ).resolve(strict=False)
    if expected_operation_id is not None and operation_id != _normalize_operation_id(
        expected_operation_id
    ):
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_operation_mismatch: paths belong to different operations."
        )
    return operation_root, operation_id


def build_etf_mins_bootstrap_plan(
    *,
    lake_root: Path,
    staging_root: Path,
    operation_id: str,
    requested_start_date: str,
    requested_end_date: str,
    created_at: datetime,
    basic_reference: EtfBasicSilverSnapshotReference,
    requestable_targets: Sequence[EtfMinsRequestableTarget],
    calendar_trade_dates: Sequence[str],
    watermark_coverages: Sequence[ProdEtfMinsFrequencyCoverage],
    free_bytes: int,
    duckdb: DuckDBResource,
    protect_from_date: str | None = None,
) -> EtfMinsBootstrapPlan:
    """Build a deterministic plan from already-frozen local and source evidence."""

    _assert_roots_available(lake_root=lake_root, staging_root=staging_root)
    started = normalize_etf_mins_trade_date(requested_start_date)
    requested_end = normalize_etf_mins_trade_date(requested_end_date)
    if started > requested_end:
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_date_range_invalid: start_date is after end_date."
        )
    normalized_created_at = _normalize_created_at(created_at)
    normalized_operation_id = _normalize_operation_id(operation_id)
    normalized_calendar_dates = _normalize_trade_dates(calendar_trade_dates)
    if not normalized_calendar_dates:
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_calendar_empty: no SSE open dates are available."
        )
    reference, normalized_targets = revalidate_etf_mins_basic_reference(
        duckdb=duckdb,
        lake_root=lake_root,
        basic_reference=basic_reference,
    )
    if tuple(normalized_targets) != tuple(requestable_targets):
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_basic_targets_changed: supplied requestable targets "
            "do not match the frozen Basic reference."
        )

    coverage_candidates = tuple(
        trade_date
        for trade_date in normalized_calendar_dates
        if trade_date <= requested_end
    )[-ETF_MINS_SENSOR_WINDOW_LIMIT:]
    if not coverage_candidates:
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_watermark_window_empty: no SSE date exists at or "
            "before the requested end date."
        )
    normalized_coverages = _normalize_watermark_coverages(
        watermark_coverages,
        expected_trade_dates=coverage_candidates,
    )
    execution_watermark = _latest_complete_watermark(
        coverage_candidates,
        normalized_coverages,
    )
    if execution_watermark is None:
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_watermark_not_ready: no five-frequency complete "
            "SSE date exists in the bounded ten-date window."
        )
    coverage_fingerprint = compute_etf_mins_bootstrap_manifest_hash(
        (
            {
                "trade_date": coverage.trade_date,
                "source_freq": coverage.source_freq,
                "expected_code_count": coverage.expected_code_count,
                "present_code_count": coverage.present_code_count,
                "missing_code_count": coverage.missing_code_count,
                "missing_code_samples": list(coverage.missing_code_samples),
                "observed_at": normalized_created_at,
            }
            for coverage in normalized_coverages
        ),
        key_fields=("trade_date", "source_freq"),
    )

    expected_trade_dates = tuple(
        trade_date
        for trade_date in normalized_calendar_dates
        if started <= trade_date <= execution_watermark
    )
    if not expected_trade_dates:
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_effective_range_empty: the dynamic watermark is "
            "earlier than the requested start date."
        )
    trimmed_trade_dates = tuple(
        trade_date
        for trade_date in normalized_calendar_dates
        if execution_watermark < trade_date <= requested_end
    )
    frequencies = tuple(ETF_MINS_SOURCE_FREQS)
    target_file_count = len(expected_trade_dates) * len(frequencies)
    raw_detail_query_count = len(frequencies) * math.ceil(
        len(expected_trade_dates) / ETF_MINS_BOOTSTRAP_BATCH_TRADE_DAY_LIMIT
    )

    raw_manifest, raw_summary = audit_etf_mins_bootstrap_targets(
        lake_root=lake_root,
        duckdb=duckdb,
        trade_dates=expected_trade_dates,
        frequencies=frequencies,
        layer="raw",
    )
    _, silver_summary = audit_etf_mins_bootstrap_targets(
        lake_root=lake_root,
        duckdb=duckdb,
        trade_dates=expected_trade_dates,
        frequencies=frequencies,
        layer="silver",
    )
    protection_mode, protected_manifest, protected_hash = (
        _build_historical_protection_contract(
            lake_root=lake_root,
            requested_start_date=started,
            requested_end_date=requested_end,
            protect_from_date=protect_from_date,
        )
    )

    estimated_source_rows = len(expected_trade_dates) * (
        _ESTIMATED_SOURCE_ROWS_PER_TRADE_DATE
    )
    estimated_staging_bytes = math.ceil(
        min(
            len(expected_trade_dates),
            ETF_MINS_BOOTSTRAP_BATCH_TRADE_DAY_LIMIT,
        )
        / ETF_MINS_BOOTSTRAP_BATCH_TRADE_DAY_LIMIT
        * 7_854_190
        * _ESTIMATED_PARQUET_BYTES_PER_ROW
    )
    estimated_final_increment_bytes = (
        estimated_source_rows * _ESTIMATED_PARQUET_BYTES_PER_ROW
        if raw_summary.get("missing", 0) > 0
        else 0
    )
    required_free_bytes = math.ceil(
        (estimated_staging_bytes + estimated_final_increment_bytes)
        * ETF_MINS_BOOTSTRAP_DISK_SAFETY_MULTIPLIER
    )
    stop_reasons: list[str] = []
    if target_file_count > ETF_MINS_BOOTSTRAP_MAX_TARGET_FILES:
        stop_reasons.append("etf_mins_bootstrap_target_file_budget_exceeded")
    if raw_detail_query_count <= 0:
        stop_reasons.append("etf_mins_bootstrap_query_budget_invalid")
    if raw_summary.get("present_invalid", 0) > 0:
        stop_reasons.append("etf_mins_bootstrap_existing_raw_invalid")
    if silver_summary.get("present_invalid", 0) > 0:
        stop_reasons.append("etf_mins_bootstrap_existing_silver_invalid")
    if free_bytes < required_free_bytes:
        stop_reasons.append("etf_mins_bootstrap_disk_budget_insufficient")

    payload: dict[str, object] = {
        "bootstrap_kind": ETF_MINS_BOOTSTRAP_KIND,
        "operation_id": normalized_operation_id,
        "schema_version": ETF_MINS_BOOTSTRAP_SCHEMA_VERSION,
        "created_at": normalized_created_at,
        "requested_start_date": started,
        "requested_end_date": requested_end,
        "execution_watermark_date": execution_watermark,
        "execution_watermark_coverage_fingerprint": coverage_fingerprint,
        "expected_trade_dates": list(expected_trade_dates),
        "expected_trade_dates_hash": compute_etf_mins_bootstrap_payload_hash(
            {"trade_dates": list(expected_trade_dates)}
        ),
        "trimmed_trade_dates": list(trimmed_trade_dates),
        "frequencies": list(frequencies),
        "frequencies_hash": compute_etf_mins_bootstrap_payload_hash(
            {"frequencies": list(frequencies)}
        ),
        "plan_coverage_query_count": 1,
        "raw_detail_query_count": raw_detail_query_count,
        "expected_remote_query_count": 1 + raw_detail_query_count,
        "basic_raw_snapshot_hash": reference.raw_snapshot_hash,
        "basic_silver_content_hash": reference.silver_content_hash,
        "basic_raw_observed_at": reference.raw_observed_at,
        "basic_silver_observed_at": reference.silver_observed_at,
        "eligibility_as_of": reference.eligibility_as_of,
        "requestable_code_count": reference.requestable_code_count,
        "requestable_code_hash": reference.requestable_code_hash,
        "target_file_count": target_file_count,
        "estimated_source_rows": estimated_source_rows,
        "estimate_basis": _ESTIMATE_BASIS,
        "estimated_staging_bytes": estimated_staging_bytes,
        "estimated_final_increment_bytes": estimated_final_increment_bytes,
        "free_bytes": int(free_bytes),
        "required_free_bytes": required_free_bytes,
        "preexisting_target_state_summary": dict(raw_summary),
        "preexisting_target_manifest": [dict(row) for row in raw_manifest],
        "preexisting_target_manifest_hash": (
            compute_etf_mins_bootstrap_manifest_hash(
                raw_manifest,
                key_fields=("source_freq", "trade_date"),
            )
        ),
        "preexisting_silver_state_summary": dict(silver_summary),
        "historical_protection_mode": protection_mode,
        "protected_file_manifest": [dict(row) for row in protected_manifest],
        "protected_file_manifest_hash": protected_hash,
        "should_stop": bool(stop_reasons),
        "stop_reasons": stop_reasons,
    }
    payload["plan_fingerprint"] = compute_etf_mins_bootstrap_payload_hash(payload)
    return _plan_from_payload(payload)


def run_etf_mins_bootstrap_plan(
    *,
    instance: Any,
    lake_root: Path,
    staging_root: Path,
    duckdb: DuckDBResource,
    prod_postgres: ProdPostgresResource,
    requested_start_date: str,
    requested_end_date: str,
    report_path: Path,
    protect_from_date: str | None = None,
    created_at: datetime | None = None,
) -> EtfMinsBootstrapPlan:
    """Run the one-query read-only plan workflow and persist its immutable report."""

    operation_root, operation_id = validate_etf_mins_bootstrap_operation_path(
        report_path,
        staging_root=staging_root,
    )
    _assert_roots_available(lake_root=lake_root, staging_root=staging_root)
    observed_at = created_at or datetime.now(ZoneInfo("Asia/Shanghai"))
    freshness_date = observed_at.astimezone(ZoneInfo("Asia/Shanghai")).date()
    reference = select_latest_etf_basic_snapshot_reference(
        instance=instance,
        lake_root_path=lake_root,
        duckdb_resource=duckdb,
        eligibility_as_of=freshness_date,
        required_freshness_date=freshness_date,
    )
    reference, requestable_targets = revalidate_etf_mins_basic_reference(
        duckdb=duckdb,
        lake_root=lake_root,
        basic_reference=reference,
    )
    calendar_dates = load_etf_mins_bootstrap_trade_dates(
        lake_root=lake_root,
        duckdb=duckdb,
    )
    requested_end = normalize_etf_mins_trade_date(requested_end_date)
    coverage_dates = tuple(
        trade_date for trade_date in calendar_dates if trade_date <= requested_end
    )[-ETF_MINS_SENSOR_WINDOW_LIMIT:]
    if not coverage_dates:
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_watermark_window_empty: no SSE open date exists."
        )
    try:
        coverages = load_prod_etf_mins_code_coverage(
            prod_postgres=prod_postgres,
            trade_dates=coverage_dates,
            requestable_targets=requestable_targets,
        )
    except Exception:  # noqa: BLE001 - sanitize all source connection failures.
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_watermark_query_failed: the one bounded Prod "
            "coverage query failed; connection details are omitted."
        ) from None
    plan = build_etf_mins_bootstrap_plan(
        lake_root=lake_root,
        staging_root=staging_root,
        operation_id=operation_id,
        requested_start_date=requested_start_date,
        requested_end_date=requested_end_date,
        created_at=observed_at,
        basic_reference=reference,
        requestable_targets=requestable_targets,
        calendar_trade_dates=calendar_dates,
        watermark_coverages=coverages,
        free_bytes=shutil.disk_usage(staging_root).free,
        duckdb=duckdb,
        protect_from_date=protect_from_date,
    )
    if operation_root != operation_root_for_etf_mins_bootstrap(
        staging_root=staging_root,
        operation_id=plan.operation_id,
    ).resolve(strict=False):
        raise EtfMinsBootstrapError("etf_mins_bootstrap_operation_mismatch.")
    write_etf_mins_bootstrap_plan(report_path, plan)
    return plan


def write_etf_mins_bootstrap_plan(
    report_path: Path,
    plan: EtfMinsBootstrapPlan,
) -> None:
    _write_immutable_json(report_path, plan.to_dict())


def load_etf_mins_bootstrap_plan(
    plan_path: Path,
    *,
    staging_root: Path,
) -> EtfMinsBootstrapPlan:
    payload = _load_json(plan_path, label="ETF minute Bootstrap plan")
    plan = _plan_from_payload(payload)
    validate_etf_mins_bootstrap_operation_path(
        plan_path,
        staging_root=staging_root,
        expected_operation_id=plan.operation_id,
    )
    if plan.should_stop:
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_plan_stopped: " + ",".join(plan.stop_reasons)
        )
    return plan


def load_etf_mins_bootstrap_trade_dates(
    *,
    lake_root: Path,
    duckdb: DuckDBResource,
) -> tuple[str, ...]:
    calendar_path = silver_trade_calendar_path(lake_root)
    if not calendar_path.is_file():
        raise EtfMinsBootstrapError(
            f"etf_mins_bootstrap_calendar_missing: {calendar_path}."
        )
    try:
        with duckdb.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT strftime(CAST(trade_date AS DATE), '%Y-%m-%d')
                FROM {read_parquet(calendar_path, hive_partitioning=False)}
                WHERE CAST(exchange AS VARCHAR) = 'SSE'
                  AND CAST(is_open AS BOOLEAN)
                GROUP BY CAST(trade_date AS DATE)
                ORDER BY CAST(trade_date AS DATE)
                """
            ).fetchall()
    except Exception:  # noqa: BLE001 - normalize local calendar failures.
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_calendar_invalid: the Silver trade calendar cannot "
            "be read with the required SSE/open contract."
        ) from None
    return _normalize_trade_dates(tuple(str(row[0]) for row in rows))


def load_etf_mins_bootstrap_raw_evidence(
    *,
    lake_root: Path,
    duckdb: DuckDBResource,
    raw_final_report_path: Path,
) -> EtfMinsBootstrapRawEvidence:
    """Load one completed Raw operation without guessing sibling artifact names."""

    if not raw_final_report_path.is_absolute():
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_raw_report_not_absolute: an explicit absolute path "
            "is required."
        )
    operation_root = raw_final_report_path.parent.resolve(strict=False)
    if (
        raw_final_report_path.name != "raw_final_report.json"
        or not operation_root.name.startswith("operation_id=")
        or operation_root.parent.name != "etf_mins"
    ):
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_raw_report_path_invalid: expected an operation-root "
            "raw_final_report.json."
        )
    staging_root = operation_root.parent.parent
    _, path_operation_id = validate_etf_mins_bootstrap_operation_path(
        raw_final_report_path,
        staging_root=staging_root,
    )
    payload = _load_json(raw_final_report_path, label="ETF minute Raw final report")
    if payload.get("bootstrap_kind") != ETF_MINS_BOOTSTRAP_KIND:
        raise EtfMinsBootstrapError("etf_mins_bootstrap_raw_report_kind_invalid.")
    if int(payload.get("schema_version", 0)) != ETF_MINS_BOOTSTRAP_SCHEMA_VERSION:
        raise EtfMinsBootstrapError("etf_mins_bootstrap_raw_report_schema_invalid.")
    if str(payload.get("operation_id") or "") != path_operation_id:
        raise EtfMinsBootstrapError("etf_mins_bootstrap_raw_report_operation_mismatch.")
    if (
        payload.get("policy_state") != "unclassified"
        or payload.get("silver_eligible") is not False
    ):
        raise EtfMinsBootstrapError("etf_mins_bootstrap_raw_report_policy_invalid.")

    provisional_report = _raw_apply_report_from_payload(
        payload,
        raw_final_report_path,
    )
    plan = load_etf_mins_bootstrap_plan(
        provisional_report.plan_path,
        staging_root=staging_root,
    )
    if plan.operation_id != path_operation_id:
        raise EtfMinsBootstrapError("etf_mins_bootstrap_raw_report_plan_mismatch.")
    basic_reference = _basic_reference_from_plan(plan, lake_root=lake_root)
    basic_reference, _ = revalidate_etf_mins_basic_reference(
        duckdb=duckdb,
        lake_root=lake_root,
        basic_reference=basic_reference,
    )
    _assert_protected_manifest_unchanged(plan=plan, lake_root=lake_root)
    raw_apply_report = _load_completed_raw_apply_report(
        plan=plan,
        plan_path=provisional_report.plan_path,
        lake_root=lake_root,
        duckdb=duckdb,
        finalized_manifest_path=provisional_report.finalized_raw_manifest_path,
        raw_final_report_path=raw_final_report_path,
        checkpoint_path=provisional_report.checkpoint_path,
    )
    manifest_rows = _load_finalized_raw_manifest(
        path=raw_apply_report.finalized_raw_manifest_path,
        duckdb=duckdb,
    )
    _assert_finalized_raw_evidence_closed(
        plan=plan,
        report=raw_apply_report,
        manifest_rows=manifest_rows,
    )
    calendar_trade_dates = set(
        load_etf_mins_bootstrap_trade_dates(lake_root=lake_root, duckdb=duckdb)
    )
    missing_calendar_dates = tuple(
        trade_date
        for trade_date in plan.expected_trade_dates
        if trade_date not in calendar_trade_dates
    )
    if missing_calendar_dates:
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_calendar_scope_changed: frozen dates are no longer "
            "SSE open dates."
        )
    return EtfMinsBootstrapRawEvidence(
        plan=plan,
        raw_apply_report=raw_apply_report,
        basic_reference=basic_reference,
        finalized_raw_manifest=manifest_rows,
    )


def audit_etf_mins_bootstrap_targets(
    *,
    lake_root: Path,
    duckdb: DuckDBResource,
    trade_dates: Sequence[str],
    frequencies: Sequence[str],
    layer: str,
) -> tuple[tuple[Mapping[str, object], ...], Mapping[str, int]]:
    """Batch-audit target structure without claiming source equivalence."""

    normalized_dates = _normalize_trade_dates(trade_dates)
    normalized_frequencies = tuple(
        normalize_etf_mins_source_freq(freq) for freq in frequencies
    )
    if layer not in {"raw", "silver"}:
        raise EtfMinsBootstrapError("etf_mins_bootstrap_target_layer_invalid.")
    rows: list[dict[str, object]] = []
    existing_paths: list[Path] = []
    expected_by_path: dict[str, tuple[str, str]] = {}
    for source_freq in normalized_frequencies:
        for trade_date in normalized_dates:
            path = (
                raw_etf_mins_path(lake_root, source_freq, trade_date)
                if layer == "raw"
                else silver_etf_mins_path(lake_root, source_freq, trade_date)
            )
            relative_path = path.relative_to(lake_root).as_posix()
            if not path.exists():
                rows.append(
                    {
                        "layer": layer,
                        "source_freq": source_freq,
                        "trade_date": trade_date,
                        "relative_path": relative_path,
                        "state": "missing",
                        "row_count": None,
                        "reason_code": None,
                    }
                )
                continue
            if not path.is_file():
                rows.append(
                    {
                        "layer": layer,
                        "source_freq": source_freq,
                        "trade_date": trade_date,
                        "relative_path": relative_path,
                        "state": "present_invalid",
                        "row_count": None,
                        "reason_code": "etf_mins_target_not_regular_file",
                    }
                )
                continue
            existing_paths.append(path)
            expected_by_path[str(path)] = (source_freq, trade_date)

    metrics_by_path: dict[str, tuple[int, int, int, int, int]] = {}
    invalid_reason_by_path: dict[str, str] = {}
    if existing_paths:
        try:
            with duckdb.connect() as connection:
                schema_by_path: dict[str, list[tuple[str, str]]] = {
                    str(path): [] for path in existing_paths
                }
                for file_name, column_name, duckdb_type in connection.execute(
                    "SELECT file_name, name, upper(duckdb_type) "
                    f"FROM parquet_schema({_duckdb_path_list(existing_paths)}) "
                    "WHERE num_children IS NULL ORDER BY file_name, column_id"
                ).fetchall():
                    schema_by_path[str(file_name)].append(
                        (str(column_name), str(duckdb_type))
                    )
                structurally_typed_paths = tuple(
                    path
                    for path in existing_paths
                    if tuple(schema_by_path.get(str(path), ())) == _RAW_SCHEMA
                )
                for path in existing_paths:
                    if path not in structurally_typed_paths:
                        invalid_reason_by_path[str(path)] = (
                            "etf_mins_target_schema_invalid"
                        )
                if structurally_typed_paths:
                    parquet_relation = _read_parquet_paths(structurally_typed_paths)
                    metric_rows = connection.execute(
                        f"""
                        WITH expected(filename, source_freq, trade_date) AS (
                          VALUES {
                            _target_expected_values(
                                structurally_typed_paths,
                                expected_by_path,
                            )
                        }
                        ),
                        rows AS (
                          SELECT * FROM {parquet_relation}
                        ),
                        duplicate_counts AS (
                          SELECT filename, sum(row_count - 1) AS duplicate_count
                          FROM (
                            SELECT filename, ts_code, freq, trade_time,
                                   count(*) AS row_count
                            FROM rows
                            GROUP BY filename, ts_code, freq, trade_time
                            HAVING count(*) > 1
                          )
                          GROUP BY filename
                        )
                        SELECT
                          expected.filename,
                          count(rows.filename) AS row_count,
                          count(*) FILTER (
                            WHERE rows.filename IS NOT NULL
                              AND (
                                ts_code IS NULL OR freq IS NULL OR trade_time IS NULL
                              )
                          ) AS null_key_count,
                          coalesce(max(duplicate_counts.duplicate_count), 0)
                            AS duplicate_key_count,
                          count(*) FILTER (
                            WHERE rows.filename IS NOT NULL
                              AND CAST(trade_time AS DATE)
                                  <> CAST(expected.trade_date AS DATE)
                          ) AS date_mismatch_count,
                          count(*) FILTER (
                            WHERE rows.filename IS NOT NULL
                              AND freq <> expected.source_freq
                          ) AS freq_mismatch_count
                        FROM expected
                        LEFT JOIN rows
                          ON rows.filename = expected.filename
                        LEFT JOIN duplicate_counts
                          ON expected.filename = duplicate_counts.filename
                        GROUP BY expected.filename
                        """
                    ).fetchall()
                    metrics_by_path = {
                        str(row[0]): tuple(int(value) for value in row[1:6])
                        for row in metric_rows
                    }
        except Exception:  # noqa: BLE001 - one batch error marks targets invalid.
            invalid_reason_by_path.update(
                {str(path): "etf_mins_target_unreadable" for path in existing_paths}
            )

    existing_row_keys = {
        (str(row["source_freq"]), str(row["trade_date"])) for row in rows
    }
    for path in existing_paths:
        source_freq, trade_date = expected_by_path[str(path)]
        if (source_freq, trade_date) in existing_row_keys:
            continue
        metrics = metrics_by_path.get(str(path))
        reason_code = invalid_reason_by_path.get(str(path))
        row_count: int | None = None
        state = "present_invalid"
        if reason_code is None and metrics is not None:
            row_count, null_keys, duplicate_keys, date_mismatch, freq_mismatch = metrics
            if not any((null_keys, duplicate_keys, date_mismatch, freq_mismatch)):
                state = "present_structurally_valid_uncompared"
                reason_code = None
            else:
                reason_code = "etf_mins_target_key_or_partition_invalid"
        rows.append(
            {
                "layer": layer,
                "source_freq": source_freq,
                "trade_date": trade_date,
                "relative_path": path.relative_to(lake_root).as_posix(),
                "state": state,
                "row_count": row_count,
                "reason_code": reason_code,
            }
        )
    ordered_rows = tuple(
        sorted(rows, key=lambda row: (str(row["source_freq"]), str(row["trade_date"])))
    )
    summary_counter = Counter(str(row["state"]) for row in ordered_rows)
    summary = {
        state: int(summary_counter.get(state, 0))
        for state in ETF_MINS_BOOTSTRAP_TARGET_STATES
    }
    return ordered_rows, summary


def apply_etf_mins_bootstrap_raw(
    *,
    lake_root: Path,
    staging_root: Path,
    duckdb: DuckDBResource,
    prod_postgres: ProdPostgresResource,
    plan_path: Path,
    checkpoint_path: Path,
    raw_final_report_path: Path,
    confirm_raw_lake_write: bool,
) -> EtfMinsBootstrapRawApplyReport:
    """Apply one approved frozen plan without re-probing Prod coverage."""

    if not confirm_raw_lake_write:
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_raw_confirmation_required: pass the explicit Raw "
            "Lake write confirmation."
        )
    _assert_roots_available(lake_root=lake_root, staging_root=staging_root)
    plan = load_etf_mins_bootstrap_plan(plan_path, staging_root=staging_root)
    operation_root, _ = validate_etf_mins_bootstrap_operation_path(
        checkpoint_path,
        staging_root=staging_root,
        expected_operation_id=plan.operation_id,
    )
    report_operation_root, _ = validate_etf_mins_bootstrap_operation_path(
        raw_final_report_path,
        staging_root=staging_root,
        expected_operation_id=plan.operation_id,
    )
    if operation_root != report_operation_root:
        raise EtfMinsBootstrapError("etf_mins_bootstrap_operation_mismatch.")
    if raw_final_report_path.parent.resolve(strict=False) != operation_root:
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_raw_report_path_invalid: raw_final_report.json must "
            "be written directly in the frozen operation directory."
        )
    if raw_final_report_path.name != "raw_final_report.json":
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_raw_report_name_invalid: expected raw_final_report.json."
        )
    finalized_manifest_path = operation_root / "finalized_raw_manifest.parquet"
    basic_reference = _basic_reference_from_plan(plan, lake_root=lake_root)
    basic_reference, _ = revalidate_etf_mins_basic_reference(
        duckdb=duckdb,
        lake_root=lake_root,
        basic_reference=basic_reference,
    )
    _assert_protected_manifest_unchanged(plan=plan, lake_root=lake_root)
    if raw_final_report_path.exists():
        return _load_completed_raw_apply_report(
            plan=plan,
            plan_path=plan_path,
            lake_root=lake_root,
            duckdb=duckdb,
            finalized_manifest_path=finalized_manifest_path,
            raw_final_report_path=raw_final_report_path,
            checkpoint_path=checkpoint_path,
        )

    checkpoint = _load_or_initialize_checkpoint(
        checkpoint_path=checkpoint_path,
        plan=plan,
    )
    validate_prod_etf_mins_select_contract()
    validate_prod_etf_mins_duckdb_contract()

    date_batches = tuple(
        _chunks(
            plan.expected_trade_dates,
            ETF_MINS_BOOTSTRAP_BATCH_TRADE_DAY_LIMIT,
        )
    )
    basic_reference_is_current = True
    for source_freq in plan.frequencies:
        for date_batch in date_batches:
            if _batch_targets_are_completed(
                checkpoint,
                source_freq=source_freq,
                trade_dates=date_batch,
            ):
                _assert_completed_batch_targets_unchanged(
                    checkpoint=checkpoint,
                    lake_root=lake_root,
                    source_freq=source_freq,
                    trade_dates=date_batch,
                )
                _cleanup_completed_source_batch(
                    operation_root=operation_root,
                    plan=plan,
                    source_freq=source_freq,
                    trade_dates=date_batch,
                )
                continue
            if not basic_reference_is_current:
                basic_reference, _ = revalidate_etf_mins_basic_reference(
                    duckdb=duckdb,
                    lake_root=lake_root,
                    basic_reference=basic_reference,
                )
            basic_reference_is_current = False
            with duckdb.connect() as connection:
                receipt = _ensure_etf_mins_source_batch(
                    connection=connection,
                    operation_root=operation_root,
                    plan=plan,
                    prod_postgres=prod_postgres,
                    source_freq=source_freq,
                    trade_dates=date_batch,
                )
                _merge_source_receipt_into_checkpoint(
                    checkpoint,
                    receipt=receipt,
                )
                _write_checkpoint(checkpoint_path, checkpoint)
                if (
                    int(receipt["source_assigned_row_count"])
                    != int(receipt["source_row_count"])
                    or int(receipt["unexpected_trade_date_count"]) != 0
                ):
                    raise EtfMinsBootstrapError(
                        "etf_mins_bootstrap_source_scope_invalid: source rows did not "
                        "map exactly to the frozen trade dates."
                    )
                create_etf_mins_frozen_basic_relations(
                    connection,
                    basic_reference=basic_reference,
                )
                for trade_date in date_batch:
                    target_record = _apply_one_etf_mins_raw_target(
                        connection=connection,
                        lake_root=lake_root,
                        staging_root=staging_root,
                        plan=plan,
                        checkpoint=checkpoint,
                        source_freq=source_freq,
                        trade_date=trade_date,
                    )
                    completed_targets = checkpoint["completed_targets"]
                    if not isinstance(completed_targets, dict):
                        raise EtfMinsBootstrapError(
                            "etf_mins_bootstrap_checkpoint_invalid: completed_targets."
                        )
                    completed_targets[_target_key(source_freq, trade_date)] = (
                        target_record
                    )
                    _update_source_batch_summary(
                        checkpoint,
                        source_freq=source_freq,
                        trade_dates=date_batch,
                    )
                    _write_checkpoint(checkpoint_path, checkpoint)
            _cleanup_completed_source_batch(
                operation_root=operation_root,
                plan=plan,
                source_freq=source_freq,
                trade_dates=date_batch,
            )

    expected_target_keys = {
        _target_key(source_freq, trade_date)
        for source_freq in plan.frequencies
        for trade_date in plan.expected_trade_dates
    }
    completed_targets = checkpoint.get("completed_targets")
    if not isinstance(completed_targets, dict) or set(completed_targets) != (
        expected_target_keys
    ):
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_targets_incomplete: final outputs are withheld until "
            "every frozen target is closed."
        )
    _assert_source_batch_summaries_closed(
        checkpoint,
        frequencies=plan.frequencies,
        date_batches=date_batches,
    )
    manifest_rows = tuple(
        dict(completed_targets[key]) for key in sorted(completed_targets)
    )
    actual_remote_query_count = _actual_remote_query_count(checkpoint)
    if actual_remote_query_count != plan.raw_detail_query_count:
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_query_budget_mismatch: source batch receipts do not "
            "match the frozen detail-query budget."
        )
    manifest_hash = compute_etf_mins_bootstrap_manifest_hash(
        manifest_rows,
        key_fields=("source_freq", "trade_date"),
    )
    _write_or_validate_finalized_raw_manifest(
        path=finalized_manifest_path,
        rows=manifest_rows,
        expected_hash=manifest_hash,
        duckdb=duckdb,
    )
    _assert_finalized_raw_files(
        plan=plan,
        lake_root=lake_root,
        manifest_rows=manifest_rows,
    )
    _assert_protected_manifest_unchanged(plan=plan, lake_root=lake_root)
    checkpoint_hash = _checkpoint_hash(checkpoint)
    source_batches = checkpoint.get("source_batches")
    if not isinstance(source_batches, dict):
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_checkpoint_invalid: source_batches."
        )
    initially_missing_targets = {
        _target_key(str(row["source_freq"]), str(row["trade_date"]))
        for row in plan.preexisting_target_manifest
        if str(row["state"]) == "missing"
    }
    report_payload: dict[str, object] = {
        "bootstrap_kind": ETF_MINS_BOOTSTRAP_KIND,
        "schema_version": ETF_MINS_BOOTSTRAP_SCHEMA_VERSION,
        "operation_id": plan.operation_id,
        "plan_fingerprint": plan.plan_fingerprint,
        "plan_relative_path": plan_path.resolve(strict=False)
        .relative_to(operation_root)
        .as_posix(),
        "checkpoint_relative_path": checkpoint_path.resolve(strict=False)
        .relative_to(operation_root)
        .as_posix(),
        "finalized_raw_manifest_relative_path": (
            finalized_manifest_path.relative_to(operation_root).as_posix()
        ),
        "finalized_raw_manifest_hash": manifest_hash,
        "source_row_count": sum(
            int(receipt["source_row_count"])
            for receipt in source_batches.values()
            if isinstance(receipt, Mapping)
        ),
        "staging_row_count": sum(
            int(row["staging_row_count"]) for row in manifest_rows
        ),
        "formal_raw_row_count": sum(
            int(row["formal_raw_row_count"]) for row in manifest_rows
        ),
        "added_file_count": sum(
            str(row["disposition"]) == "added" for row in manifest_rows
        ),
        "reused_file_count": sum(
            str(row["disposition"]) == "reused" for row in manifest_rows
        ),
        "zero_row_file_count": sum(bool(row["zero_row"]) for row in manifest_rows),
        "actual_remote_query_count": actual_remote_query_count,
        "temporary_space_peak_bytes": max(
            int(receipt["temporary_space_peak_bytes"])
            for receipt in source_batches.values()
            if isinstance(receipt, Mapping)
        ),
        "final_space_increment_bytes": sum(
            int(row["formal_raw_size_bytes"])
            for row in manifest_rows
            if _target_key(str(row["source_freq"]), str(row["trade_date"]))
            in initially_missing_targets
        ),
        "checkpoint_hash": checkpoint_hash,
        "historical_protection_mode": plan.historical_protection_mode,
        "protected_file_manifest_hash_before": plan.protected_file_manifest_hash,
        "protected_file_manifest_hash_after": plan.protected_file_manifest_hash,
        "policy_state": "unclassified",
        "silver_eligible": False,
    }
    report_payload["report_hash"] = compute_etf_mins_bootstrap_payload_hash(
        report_payload
    )
    _write_immutable_json(raw_final_report_path, report_payload)
    return _raw_apply_report_from_payload(report_payload, raw_final_report_path)


def apply_etf_mins_bootstrap_silver(
    *,
    lake_root: Path,
    staging_root: Path,
    duckdb: DuckDBResource,
    raw_decision_summary_path: Path,
    decision_manifest_path: Path,
    checkpoint_path: Path,
    final_report_path: Path,
    confirm_silver_lake_write: bool,
) -> EtfMinsBootstrapSilverApplyReport:
    """Publish only N3-admitted Raw partitions as exact Silver copies."""

    if not confirm_silver_lake_write:
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_silver_confirmation_required: pass the explicit "
            "Silver Lake write confirmation."
        )
    _assert_roots_available(lake_root=lake_root, staging_root=staging_root)
    operation_root, operation_id = validate_etf_mins_bootstrap_operation_path(
        raw_decision_summary_path,
        staging_root=staging_root,
    )
    for path in (decision_manifest_path, checkpoint_path, final_report_path):
        candidate_root, _ = validate_etf_mins_bootstrap_operation_path(
            path,
            staging_root=staging_root,
            expected_operation_id=operation_id,
        )
        if candidate_root != operation_root:
            raise EtfMinsBootstrapError("etf_mins_bootstrap_operation_mismatch.")
    expected_names = {
        raw_decision_summary_path: "raw_decision_summary.json",
        decision_manifest_path: "raw_partition_decision_manifest.parquet",
        checkpoint_path: _SILVER_CHECKPOINT_FILENAME,
        final_report_path: _PHYSICAL_FINAL_REPORT_FILENAME,
    }
    if any(
        path.parent.resolve(strict=False) != operation_root
        or path.name != expected_name
        for path, expected_name in expected_names.items()
    ):
        raise EtfMinsBootstrapError("etf_mins_bootstrap_silver_artifact_path_invalid.")

    raw_evidence = load_etf_mins_bootstrap_raw_evidence(
        lake_root=lake_root,
        duckdb=duckdb,
        raw_final_report_path=operation_root / "raw_final_report.json",
    )
    if raw_evidence.plan.operation_id != operation_id:
        raise EtfMinsBootstrapError("etf_mins_bootstrap_silver_operation_mismatch.")
    decision_summary, decision_rows, observation_summary_hash = (
        _load_etf_mins_silver_decision_evidence(
            operation_root=operation_root,
            operation_id=operation_id,
            raw_evidence=raw_evidence,
            decision_summary_path=raw_decision_summary_path,
            decision_manifest_path=decision_manifest_path,
            duckdb=duckdb,
        )
    )
    policy = get_etf_mins_raw_decision_policy(
        str(decision_summary["approved_policy_version"])
    )
    raw_rows_by_key = {
        _target_key(str(row["source_freq"]), str(row["trade_date"])): row
        for row in raw_evidence.finalized_raw_manifest
    }
    decision_rows_by_key = {
        _target_key(str(row["source_freq"]), str(row["trade_date"])): row
        for row in decision_rows
    }
    _assert_etf_mins_silver_decision_scope(
        raw_rows_by_key=raw_rows_by_key,
        decision_rows_by_key=decision_rows_by_key,
        raw_evidence=raw_evidence,
        policy=policy,
    )
    _assert_protected_manifest_unchanged(
        plan=raw_evidence.plan,
        lake_root=lake_root,
    )

    for key, decision_row in decision_rows_by_key.items():
        if bool(decision_row["silver_eligible"]):
            continue
        raw_row = raw_rows_by_key[key]
        blocked_target = silver_etf_mins_path(
            lake_root,
            str(raw_row["source_freq"]),
            str(raw_row["trade_date"]),
        )
        if blocked_target.exists():
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_blocked_silver_target_present: blocked/unknown "
                "partitions must have no Silver file."
            )

    work_manifest_path = operation_root / _SILVER_WORK_MANIFEST_FILENAME
    work_rows = _load_or_create_etf_mins_silver_work_manifest(
        path=work_manifest_path,
        lake_root=lake_root,
        duckdb=duckdb,
        raw_evidence=raw_evidence,
        raw_rows_by_key=raw_rows_by_key,
        decision_rows_by_key=decision_rows_by_key,
        policy=policy,
    )
    work_manifest_hash = compute_etf_mins_bootstrap_manifest_hash(
        work_rows,
        key_fields=("source_freq", "trade_date"),
    )
    checkpoint = _load_or_initialize_etf_mins_silver_checkpoint(
        checkpoint_path=checkpoint_path,
        raw_evidence=raw_evidence,
        decision_summary=decision_summary,
        work_manifest_hash=work_manifest_hash,
    )
    completed_targets = checkpoint["completed_targets"]
    if not isinstance(completed_targets, dict):
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_silver_checkpoint_invalid: completed_targets."
        )

    for work_row in work_rows:
        source_freq = str(work_row["source_freq"])
        trade_date = str(work_row["trade_date"])
        target_key = _target_key(source_freq, trade_date)
        raw_path = raw_etf_mins_path(lake_root, source_freq, trade_date)
        if (
            not raw_path.is_file()
            or _sha256_file(raw_path) != work_row["formal_raw_sha256"]
        ):
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_silver_raw_changed_before_copy."
            )
        if target_key in completed_targets:
            _assert_etf_mins_completed_silver_target(
                lake_root=lake_root,
                duckdb=duckdb,
                work_row=work_row,
                completed_row=completed_targets[target_key],
            )
            stale_candidate = etf_mins_staging_path(
                staging_root,
                operation_id,
                "silver",
                source_freq,
                trade_date,
            )
            if stale_candidate.exists():
                _assert_etf_mins_silver_candidate_equivalent(
                    duckdb=duckdb,
                    raw_path=raw_path,
                    candidate_path=stale_candidate,
                )
                stale_candidate.unlink()
            continue
        completed_targets[target_key] = _apply_one_etf_mins_silver_target(
            lake_root=lake_root,
            staging_root=staging_root,
            duckdb=duckdb,
            operation_id=operation_id,
            work_row=work_row,
        )
        _write_etf_mins_silver_checkpoint(checkpoint_path, checkpoint)

    expected_work_keys = {
        _target_key(str(row["source_freq"]), str(row["trade_date"]))
        for row in work_rows
    }
    if set(completed_targets) != expected_work_keys:
        raise EtfMinsBootstrapError("etf_mins_bootstrap_silver_targets_incomplete.")
    finalized_rows = tuple(
        dict(completed_targets[key]) for key in sorted(completed_targets)
    )
    finalized_manifest_path = operation_root / _FINALIZED_SILVER_MANIFEST_FILENAME
    _write_or_validate_etf_mins_typed_manifest(
        path=finalized_manifest_path,
        rows=finalized_rows,
        columns=_FINALIZED_SILVER_MANIFEST_COLUMNS,
        duckdb=duckdb,
    )
    finalized_manifest_hash = compute_etf_mins_bootstrap_manifest_hash(
        finalized_rows,
        key_fields=("source_freq", "trade_date"),
    )
    checkpoint_hash = _validate_etf_mins_silver_checkpoint(
        checkpoint,
        raw_evidence=raw_evidence,
        decision_summary=decision_summary,
        work_manifest_hash=work_manifest_hash,
    )
    _assert_etf_mins_silver_physical_closure(
        lake_root=lake_root,
        staging_root=staging_root,
        duckdb=duckdb,
        raw_evidence=raw_evidence,
        raw_rows_by_key=raw_rows_by_key,
        decision_rows_by_key=decision_rows_by_key,
        work_rows=work_rows,
        finalized_rows=finalized_rows,
        checkpoint=checkpoint,
    )
    _assert_protected_manifest_unchanged(
        plan=raw_evidence.plan,
        lake_root=lake_root,
    )

    report_payload: dict[str, object] = {
        "bootstrap_kind": ETF_MINS_BOOTSTRAP_KIND,
        "schema_version": ETF_MINS_BOOTSTRAP_SCHEMA_VERSION,
        "operation_id": operation_id,
        "plan_fingerprint": raw_evidence.plan.plan_fingerprint,
        "raw_final_report_hash": raw_evidence.raw_apply_report.report_hash,
        "raw_observation_summary_hash": observation_summary_hash,
        "raw_decision_summary_hash": str(decision_summary["raw_decision_summary_hash"]),
        "raw_partition_decision_manifest_hash": str(
            decision_summary["raw_partition_decision_manifest"]["sha256"]
        ),
        "finalized_raw_manifest_hash": (
            raw_evidence.raw_apply_report.finalized_raw_manifest_hash
        ),
        "silver_work_manifest_relative_path": work_manifest_path.name,
        "silver_work_manifest_hash": work_manifest_hash,
        "finalized_silver_manifest_relative_path": finalized_manifest_path.name,
        "finalized_silver_manifest_hash": finalized_manifest_hash,
        "silver_checkpoint_relative_path": checkpoint_path.name,
        "checkpoint_hash": checkpoint_hash,
        "basic_raw_snapshot_hash": raw_evidence.plan.basic_raw_snapshot_hash,
        "basic_silver_content_hash": raw_evidence.plan.basic_silver_content_hash,
        "gap_policy_version": policy.version,
        "gap_policy_hash": policy.policy_hash,
        "historical_protection_mode": raw_evidence.plan.historical_protection_mode,
        "protected_file_manifest_hash": (
            raw_evidence.plan.protected_file_manifest_hash
        ),
        "raw_file_count": len(raw_evidence.finalized_raw_manifest),
        "raw_row_count": sum(
            int(row["formal_raw_row_count"])
            for row in raw_evidence.finalized_raw_manifest
        ),
        "silver_file_count": len(finalized_rows),
        "silver_row_count": sum(
            int(row["formal_silver_row_count"]) for row in finalized_rows
        ),
        "added_file_count": sum(
            row["disposition"] == "added" for row in finalized_rows
        ),
        "reused_file_count": sum(
            row["disposition"] == "reused" for row in finalized_rows
        ),
        "blocked_partition_count": sum(
            row["decision"] == "blocked" for row in decision_rows
        ),
        "warn_partition_count": sum(row["decision"] == "warn" for row in decision_rows),
    }
    report_payload["report_hash"] = compute_etf_mins_bootstrap_payload_hash(
        report_payload
    )
    _write_immutable_json(final_report_path, report_payload)
    return _silver_apply_report_from_payload(report_payload, final_report_path)


def _load_etf_mins_silver_decision_evidence(
    *,
    operation_root: Path,
    operation_id: str,
    raw_evidence: EtfMinsBootstrapRawEvidence,
    decision_summary_path: Path,
    decision_manifest_path: Path,
    duckdb: DuckDBResource,
) -> tuple[dict[str, Any], tuple[dict[str, object], ...], str]:
    summary = _load_json(decision_summary_path, label="ETF minute Raw decision")
    expected_summary_hash = compute_etf_mins_bootstrap_payload_hash(
        summary,
        self_hash_field="raw_decision_summary_hash",
    )
    manifest_metadata = summary.get("raw_partition_decision_manifest")
    policy_version = str(summary.get("approved_policy_version") or "")
    try:
        policy = get_etf_mins_raw_decision_policy(policy_version)
    except ValueError as error:
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_silver_policy_not_registered."
        ) from error
    if (
        summary.get("decision_kind") != "etf_mins_raw_decision"
        or int(summary.get("schema_version", 0)) != ETF_MINS_BOOTSTRAP_SCHEMA_VERSION
        or summary.get("operation_id") != operation_id
        or summary.get("plan_fingerprint") != raw_evidence.plan.plan_fingerprint
        or summary.get("input_manifest_hash")
        != raw_evidence.raw_apply_report.finalized_raw_manifest_hash
        or summary.get("approved_policy_hash") != policy.policy_hash
        or summary.get("raw_decision_summary_hash") != expected_summary_hash
        or not isinstance(manifest_metadata, Mapping)
        or manifest_metadata.get("filename") != decision_manifest_path.name
        or not decision_manifest_path.is_file()
        or int(manifest_metadata.get("size_bytes", -1))
        != decision_manifest_path.stat().st_size
        or manifest_metadata.get("sha256") != _sha256_file(decision_manifest_path)
    ):
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_silver_decision_evidence_invalid."
        )
    observation_summary_path = (
        operation_root / "raw-observe/raw_observation_summary.json"
    )
    observation_summary = _load_json(
        observation_summary_path,
        label="ETF minute Raw observation summary",
    )
    observation_summary_hash = compute_etf_mins_bootstrap_payload_hash(
        observation_summary,
        self_hash_field="observation_summary_hash",
    )
    if (
        observation_summary.get("operation_id") != operation_id
        or observation_summary.get("plan_fingerprint")
        != raw_evidence.plan.plan_fingerprint
        or observation_summary.get("input_manifest_hash")
        != raw_evidence.raw_apply_report.finalized_raw_manifest_hash
        or observation_summary.get("observation_summary_hash")
        != observation_summary_hash
        or summary.get("observation_summary_hash") != observation_summary_hash
    ):
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_silver_observation_evidence_invalid."
        )
    selected_columns = (
        "operation_id",
        "plan_fingerprint",
        "trade_date",
        "source_freq",
        "raw_relative_path",
        "raw_sha256",
        "raw_row_count",
        "basic_raw_snapshot_hash",
        "basic_silver_content_hash",
        "approved_policy_version",
        "approved_policy_hash",
        "decision_reason_codes_json",
        "decision",
        "silver_eligible",
    )
    try:
        with duckdb.connect() as connection:
            cursor = connection.execute(
                f"SELECT {', '.join(selected_columns)} FROM "
                f"{read_parquet(decision_manifest_path, hive_partitioning=False)} "
                "ORDER BY source_freq, trade_date"
            )
            rows = tuple(
                dict(zip(selected_columns, row, strict=True))
                for row in cursor.fetchall()
            )
    except Exception:  # noqa: BLE001 - normalize decision manifest failures.
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_silver_decision_manifest_unreadable."
        ) from None
    if len(rows) != int(manifest_metadata.get("row_count", -1)):
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_silver_decision_manifest_count_invalid."
        )
    return summary, rows, observation_summary_hash


def _assert_etf_mins_silver_decision_scope(
    *,
    raw_rows_by_key: Mapping[str, Mapping[str, object]],
    decision_rows_by_key: Mapping[str, Mapping[str, object]],
    raw_evidence: EtfMinsBootstrapRawEvidence,
    policy: Any,
) -> None:
    if len(decision_rows_by_key) != len(raw_evidence.finalized_raw_manifest) or set(
        decision_rows_by_key
    ) != set(raw_rows_by_key):
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_silver_decision_scope_mismatch."
        )
    allowed_reasons = set(policy.blocking_reason_codes) | set(
        policy.warning_reason_codes
    )
    for key, decision_row in decision_rows_by_key.items():
        raw_row = raw_rows_by_key[key]
        try:
            reason_codes = json.loads(str(decision_row["decision_reason_codes_json"]))
        except json.JSONDecodeError as error:
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_silver_decision_reasons_invalid."
            ) from error
        if not isinstance(reason_codes, list) or any(
            not isinstance(reason, str) or reason not in allowed_reasons
            for reason in reason_codes
        ):
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_silver_decision_reasons_invalid."
            )
        blocking = any(
            reason in policy.blocking_reason_codes for reason in reason_codes
        )
        warning = any(reason in policy.warning_reason_codes for reason in reason_codes)
        expected_decision = "blocked" if blocking else "warn" if warning else "green"
        if (
            decision_row["operation_id"] != raw_evidence.plan.operation_id
            or decision_row["plan_fingerprint"] != raw_evidence.plan.plan_fingerprint
            or decision_row["raw_relative_path"] != raw_row["formal_raw_relative_path"]
            or decision_row["raw_sha256"] != raw_row["formal_raw_sha256"]
            or int(decision_row["raw_row_count"])
            != int(raw_row["formal_raw_row_count"])
            or decision_row["basic_raw_snapshot_hash"]
            != raw_evidence.plan.basic_raw_snapshot_hash
            or decision_row["basic_silver_content_hash"]
            != raw_evidence.plan.basic_silver_content_hash
            or decision_row["approved_policy_version"] != policy.version
            or decision_row["approved_policy_hash"] != policy.policy_hash
            or decision_row["decision"] != expected_decision
            or bool(decision_row["silver_eligible"]) != (not blocking)
        ):
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_silver_decision_row_mismatch."
            )


def _load_or_create_etf_mins_silver_work_manifest(
    *,
    path: Path,
    lake_root: Path,
    duckdb: DuckDBResource,
    raw_evidence: EtfMinsBootstrapRawEvidence,
    raw_rows_by_key: Mapping[str, Mapping[str, object]],
    decision_rows_by_key: Mapping[str, Mapping[str, object]],
    policy: Any,
) -> tuple[dict[str, object], ...]:
    expected_rows = []
    for key in sorted(decision_rows_by_key):
        decision_row = decision_rows_by_key[key]
        if not bool(decision_row["silver_eligible"]):
            continue
        raw_row = raw_rows_by_key[key]
        source_freq = str(raw_row["source_freq"])
        trade_date = str(raw_row["trade_date"])
        silver_path = silver_etf_mins_path(lake_root, source_freq, trade_date)
        expected_rows.append(
            {
                "operation_id": raw_evidence.plan.operation_id,
                "plan_fingerprint": raw_evidence.plan.plan_fingerprint,
                "source_freq": source_freq,
                "trade_date": trade_date,
                "formal_raw_relative_path": raw_row["formal_raw_relative_path"],
                "formal_raw_sha256": raw_row["formal_raw_sha256"],
                "formal_raw_row_count": int(raw_row["formal_raw_row_count"]),
                "formal_silver_relative_path": silver_path.relative_to(
                    lake_root
                ).as_posix(),
                "decision": decision_row["decision"],
                "decision_reason_codes_json": decision_row[
                    "decision_reason_codes_json"
                ],
                "approved_policy_version": policy.version,
                "approved_policy_hash": policy.policy_hash,
                "initial_silver_target_state": (
                    "present" if silver_path.exists() else "missing"
                ),
            }
        )
    if path.exists():
        observed = _load_etf_mins_typed_manifest(
            path=path,
            columns=_SILVER_WORK_MANIFEST_COLUMNS,
            duckdb=duckdb,
        )
        expected_without_state = {
            _target_key(str(row["source_freq"]), str(row["trade_date"])): {
                key: value
                for key, value in row.items()
                if key != "initial_silver_target_state"
            }
            for row in expected_rows
        }
        observed_without_state = {
            _target_key(str(row["source_freq"]), str(row["trade_date"])): {
                key: value
                for key, value in row.items()
                if key != "initial_silver_target_state"
            }
            for row in observed
        }
        if expected_without_state != observed_without_state or any(
            row["initial_silver_target_state"] not in {"missing", "present"}
            for row in observed
        ):
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_silver_work_manifest_conflict."
            )
        return observed
    rows = tuple(expected_rows)
    _write_or_validate_etf_mins_typed_manifest(
        path=path,
        rows=rows,
        columns=_SILVER_WORK_MANIFEST_COLUMNS,
        duckdb=duckdb,
    )
    return rows


def _load_or_initialize_etf_mins_silver_checkpoint(
    *,
    checkpoint_path: Path,
    raw_evidence: EtfMinsBootstrapRawEvidence,
    decision_summary: Mapping[str, object],
    work_manifest_hash: str,
) -> dict[str, object]:
    if checkpoint_path.exists():
        checkpoint = _load_json(
            checkpoint_path,
            label="ETF minute Silver checkpoint",
        )
        _validate_etf_mins_silver_checkpoint(
            checkpoint,
            raw_evidence=raw_evidence,
            decision_summary=decision_summary,
            work_manifest_hash=work_manifest_hash,
        )
        return checkpoint
    checkpoint: dict[str, object] = {
        "checkpoint_kind": "etf_mins_silver_apply_checkpoint",
        "schema_version": ETF_MINS_BOOTSTRAP_SCHEMA_VERSION,
        "operation_id": raw_evidence.plan.operation_id,
        "plan_fingerprint": raw_evidence.plan.plan_fingerprint,
        "raw_final_report_hash": raw_evidence.raw_apply_report.report_hash,
        "raw_decision_summary_hash": decision_summary["raw_decision_summary_hash"],
        "silver_work_manifest_hash": work_manifest_hash,
        "completed_targets": {},
    }
    _write_etf_mins_silver_checkpoint(checkpoint_path, checkpoint)
    return checkpoint


def _write_etf_mins_silver_checkpoint(
    checkpoint_path: Path,
    checkpoint: dict[str, object],
) -> None:
    checkpoint["checkpoint_hash"] = compute_etf_mins_bootstrap_payload_hash(
        checkpoint,
        self_hash_field="checkpoint_hash",
    )
    _atomic_write_json(checkpoint_path, checkpoint)


def _validate_etf_mins_silver_checkpoint(
    checkpoint: Mapping[str, object],
    *,
    raw_evidence: EtfMinsBootstrapRawEvidence,
    decision_summary: Mapping[str, object],
    work_manifest_hash: str,
) -> str:
    expected_hash = compute_etf_mins_bootstrap_payload_hash(
        checkpoint,
        self_hash_field="checkpoint_hash",
    )
    if (
        checkpoint.get("checkpoint_kind") != "etf_mins_silver_apply_checkpoint"
        or int(checkpoint.get("schema_version", 0)) != ETF_MINS_BOOTSTRAP_SCHEMA_VERSION
        or checkpoint.get("operation_id") != raw_evidence.plan.operation_id
        or checkpoint.get("plan_fingerprint") != raw_evidence.plan.plan_fingerprint
        or checkpoint.get("raw_final_report_hash")
        != raw_evidence.raw_apply_report.report_hash
        or checkpoint.get("raw_decision_summary_hash")
        != decision_summary["raw_decision_summary_hash"]
        or checkpoint.get("silver_work_manifest_hash") != work_manifest_hash
        or checkpoint.get("checkpoint_hash") != expected_hash
        or not isinstance(checkpoint.get("completed_targets"), Mapping)
    ):
        raise EtfMinsBootstrapError("etf_mins_bootstrap_silver_checkpoint_invalid.")
    return expected_hash


def _apply_one_etf_mins_silver_target(
    *,
    lake_root: Path,
    staging_root: Path,
    duckdb: DuckDBResource,
    operation_id: str,
    work_row: Mapping[str, object],
) -> dict[str, object]:
    source_freq = str(work_row["source_freq"])
    trade_date = str(work_row["trade_date"])
    raw_path = raw_etf_mins_path(lake_root, source_freq, trade_date)
    target_path = silver_etf_mins_path(lake_root, source_freq, trade_date)
    candidate_path = etf_mins_staging_path(
        staging_root,
        operation_id,
        "silver",
        source_freq,
        trade_date,
    )
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as connection:
        raw_relation = read_parquet(raw_path, hive_partitioning=False)
        if not candidate_path.exists():
            connection.execute(
                copy_query_to_parquet(
                    build_etf_mins_silver_copy_sql(raw_relation),
                    candidate_path,
                )
            )
        _assert_exact_etf_mins_silver_candidate(
            connection=connection,
            raw_path=raw_path,
            candidate_path=candidate_path,
            expected_row_count=int(work_row["formal_raw_row_count"]),
        )
        candidate_relation = read_parquet(candidate_path, hive_partitioning=False)
        if target_path.exists():
            if not target_path.is_file():
                raise EtfMinsBootstrapError(
                    "etf_mins_bootstrap_silver_target_conflict."
                )
            target_relation = read_parquet(target_path, hive_partitioning=False)
            try:
                target_equal = etf_mins_relations_are_semantically_equal(
                    connection,
                    left_relation=candidate_relation,
                    right_relation=target_relation,
                )
            except Exception as error:
                raise EtfMinsBootstrapError(
                    "etf_mins_bootstrap_silver_target_conflict."
                ) from error
            if not target_equal:
                raise EtfMinsBootstrapError(
                    "etf_mins_bootstrap_silver_target_conflict."
                )
            candidate_path.unlink()
            disposition = "reused"
        else:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if target_path.exists():
                raise EtfMinsBootstrapError(
                    "etf_mins_bootstrap_silver_target_conflict."
                )
            try:
                os.replace(candidate_path, target_path)
            except OSError:
                raise EtfMinsBootstrapError(
                    "etf_mins_bootstrap_silver_atomic_promote_failed."
                ) from None
            disposition = "added"
    if not target_path.is_file():
        raise EtfMinsBootstrapError("etf_mins_bootstrap_silver_target_missing.")
    return {
        "operation_id": work_row["operation_id"],
        "plan_fingerprint": work_row["plan_fingerprint"],
        "source_freq": source_freq,
        "trade_date": trade_date,
        "formal_raw_relative_path": work_row["formal_raw_relative_path"],
        "formal_raw_sha256": work_row["formal_raw_sha256"],
        "formal_raw_row_count": int(work_row["formal_raw_row_count"]),
        "formal_silver_relative_path": target_path.relative_to(lake_root).as_posix(),
        "formal_silver_sha256": _sha256_file(target_path),
        "formal_silver_size_bytes": target_path.stat().st_size,
        "formal_silver_row_count": int(work_row["formal_raw_row_count"]),
        "disposition": disposition,
        "decision": work_row["decision"],
        "decision_reason_codes_json": work_row["decision_reason_codes_json"],
        "approved_policy_version": work_row["approved_policy_version"],
        "approved_policy_hash": work_row["approved_policy_hash"],
    }


def _assert_exact_etf_mins_silver_candidate(
    *,
    connection: Any,
    raw_path: Path,
    candidate_path: Path,
    expected_row_count: int,
) -> None:
    try:
        candidate_relation = read_parquet(candidate_path, hive_partitioning=False)
        observed_schema = tuple(
            (str(row[0]), str(row[1]).upper())
            for row in connection.execute(
                f"DESCRIBE SELECT * FROM {candidate_relation}"
            ).fetchall()
        )
        if observed_schema != _RAW_SCHEMA:
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_silver_candidate_schema_invalid."
            )
        raw_relation = read_parquet(raw_path, hive_partitioning=False)
        if not etf_mins_relations_are_semantically_equal(
            connection,
            left_relation=raw_relation,
            right_relation=candidate_relation,
        ):
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_silver_candidate_not_equal_to_raw."
            )
        row_count = int(
            connection.execute(f"SELECT count(*) FROM {candidate_relation}").fetchone()[
                0
            ]
        )
        if row_count != expected_row_count:
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_silver_candidate_row_count_invalid."
            )
    except EtfMinsBootstrapError:
        raise
    except Exception:  # noqa: BLE001 - normalize candidate failures.
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_silver_candidate_unreadable."
        ) from None


def _assert_etf_mins_silver_candidate_equivalent(
    *,
    duckdb: DuckDBResource,
    raw_path: Path,
    candidate_path: Path,
) -> None:
    with duckdb.connect() as connection:
        expected_rows = int(
            connection.execute(
                f"SELECT count(*) FROM {read_parquet(raw_path, hive_partitioning=False)}"
            ).fetchone()[0]
        )
        _assert_exact_etf_mins_silver_candidate(
            connection=connection,
            raw_path=raw_path,
            candidate_path=candidate_path,
            expected_row_count=expected_rows,
        )


def _assert_etf_mins_completed_silver_target(
    *,
    lake_root: Path,
    duckdb: DuckDBResource,
    work_row: Mapping[str, object],
    completed_row: object,
) -> None:
    if not isinstance(completed_row, Mapping):
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_silver_checkpoint_target_invalid."
        )
    source_freq = str(work_row["source_freq"])
    trade_date = str(work_row["trade_date"])
    target_path = silver_etf_mins_path(lake_root, source_freq, trade_date)
    expected_identity = {
        "operation_id": work_row["operation_id"],
        "plan_fingerprint": work_row["plan_fingerprint"],
        "source_freq": source_freq,
        "trade_date": trade_date,
        "formal_raw_relative_path": work_row["formal_raw_relative_path"],
        "formal_raw_sha256": work_row["formal_raw_sha256"],
        "formal_raw_row_count": int(work_row["formal_raw_row_count"]),
        "formal_silver_relative_path": target_path.relative_to(lake_root).as_posix(),
        "formal_silver_row_count": int(work_row["formal_raw_row_count"]),
        "decision": work_row["decision"],
        "decision_reason_codes_json": work_row["decision_reason_codes_json"],
        "approved_policy_version": work_row["approved_policy_version"],
        "approved_policy_hash": work_row["approved_policy_hash"],
    }
    if (
        any(completed_row.get(key) != value for key, value in expected_identity.items())
        or not target_path.is_file()
        or completed_row.get("formal_silver_sha256") != _sha256_file(target_path)
        or int(completed_row.get("formal_silver_size_bytes", -1))
        != target_path.stat().st_size
        or completed_row.get("disposition") not in {"added", "reused"}
    ):
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_silver_completed_target_changed."
        )
    raw_path = raw_etf_mins_path(lake_root, source_freq, trade_date)
    with duckdb.connect() as connection:
        try:
            equal = etf_mins_relations_are_semantically_equal(
                connection,
                left_relation=read_parquet(raw_path, hive_partitioning=False),
                right_relation=read_parquet(target_path, hive_partitioning=False),
            )
        except Exception as error:
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_silver_completed_target_changed."
            ) from error
    if not equal:
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_silver_completed_target_changed."
        )


def _write_or_validate_etf_mins_typed_manifest(
    *,
    path: Path,
    rows: Sequence[Mapping[str, object]],
    columns: Sequence[str],
    duckdb: DuckDBResource,
) -> None:
    if path.exists():
        observed = _load_etf_mins_typed_manifest(
            path=path,
            columns=columns,
            duckdb=duckdb,
        )
        if compute_etf_mins_bootstrap_manifest_hash(
            observed,
            key_fields=("source_freq", "trade_date"),
        ) != compute_etf_mins_bootstrap_manifest_hash(
            rows,
            key_fields=("source_freq", "trade_date"),
        ):
            raise EtfMinsBootstrapError("etf_mins_bootstrap_silver_manifest_conflict.")
        return
    if any(set(row) != set(columns) for row in rows):
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_silver_manifest_schema_invalid."
        )
    candidate = path.with_name(f".{path.name}.candidate-{uuid.uuid4().hex}")
    path.parent.mkdir(parents=True, exist_ok=True)
    schema_sql = ", ".join(
        f"{column} "
        + ("BIGINT" if column.endswith(("_count", "_bytes")) else "VARCHAR")
        for column in columns
    )
    try:
        with duckdb.connect() as connection:
            connection.execute(f"CREATE TEMP TABLE manifest ({schema_sql})")
            if rows:
                placeholders = ", ".join("?" for _ in columns)
                connection.executemany(
                    f"INSERT INTO manifest VALUES ({placeholders})",
                    [tuple(row[column] for column in columns) for row in rows],
                )
            connection.execute(
                copy_query_to_parquet(
                    "SELECT * FROM manifest ORDER BY source_freq, trade_date",
                    candidate,
                )
            )
        os.replace(candidate, path)
    finally:
        if candidate.exists():
            candidate.unlink()


def _load_etf_mins_typed_manifest(
    *,
    path: Path,
    columns: Sequence[str],
    duckdb: DuckDBResource,
) -> tuple[dict[str, object], ...]:
    try:
        with duckdb.connect() as connection:
            cursor = connection.execute(
                f"SELECT * FROM {read_parquet(path, hive_partitioning=False)} "
                "ORDER BY source_freq, trade_date"
            )
            observed_columns = tuple(str(item[0]) for item in cursor.description)
            if observed_columns != tuple(columns):
                raise EtfMinsBootstrapError(
                    "etf_mins_bootstrap_silver_manifest_schema_invalid."
                )
            return tuple(
                dict(zip(observed_columns, row, strict=True))
                for row in cursor.fetchall()
            )
    except EtfMinsBootstrapError:
        raise
    except Exception:  # noqa: BLE001 - normalize manifest read failures.
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_silver_manifest_unreadable."
        ) from None


def _assert_etf_mins_silver_physical_closure(
    *,
    lake_root: Path,
    staging_root: Path,
    duckdb: DuckDBResource,
    raw_evidence: EtfMinsBootstrapRawEvidence,
    raw_rows_by_key: Mapping[str, Mapping[str, object]],
    decision_rows_by_key: Mapping[str, Mapping[str, object]],
    work_rows: Sequence[Mapping[str, object]],
    finalized_rows: Sequence[Mapping[str, object]],
    checkpoint: Mapping[str, object],
) -> None:
    eligible_keys = {
        key for key, row in decision_rows_by_key.items() if bool(row["silver_eligible"])
    }
    work_keys = {
        _target_key(str(row["source_freq"]), str(row["trade_date"]))
        for row in work_rows
    }
    final_rows_by_key = {
        _target_key(str(row["source_freq"]), str(row["trade_date"])): row
        for row in finalized_rows
    }
    completed = checkpoint.get("completed_targets")
    if (
        work_keys != eligible_keys
        or set(final_rows_by_key) != eligible_keys
        or not isinstance(completed, Mapping)
        or set(completed) != eligible_keys
    ):
        raise EtfMinsBootstrapError("etf_mins_bootstrap_silver_physical_scope_invalid.")
    for key, raw_row in raw_rows_by_key.items():
        source_freq = str(raw_row["source_freq"])
        trade_date = str(raw_row["trade_date"])
        silver_path = silver_etf_mins_path(lake_root, source_freq, trade_date)
        if (key in eligible_keys) != silver_path.is_file():
            raise EtfMinsBootstrapError("etf_mins_bootstrap_silver_file_set_invalid.")
        if key not in eligible_keys:
            continue
        final_row = final_rows_by_key[key]
        _assert_etf_mins_completed_silver_target(
            lake_root=lake_root,
            duckdb=duckdb,
            work_row=final_row,
            completed_row=final_row,
        )
        if int(final_row["formal_silver_row_count"]) != int(
            raw_row["formal_raw_row_count"]
        ):
            raise EtfMinsBootstrapError("etf_mins_bootstrap_silver_row_count_mismatch.")
    operation_silver_root = (
        operation_root_for_etf_mins_bootstrap(
            staging_root=staging_root,
            operation_id=raw_evidence.plan.operation_id,
        )
        / "silver"
    )
    if operation_silver_root.exists() and any(
        path.is_file() for path in operation_silver_root.rglob("*")
    ):
        raise EtfMinsBootstrapError("etf_mins_bootstrap_silver_staging_not_closed.")


def _silver_apply_report_from_payload(
    payload: Mapping[str, object],
    final_report_path: Path,
) -> EtfMinsBootstrapSilverApplyReport:
    expected_hash = compute_etf_mins_bootstrap_payload_hash(
        payload,
        self_hash_field="report_hash",
    )
    if payload.get("report_hash") != expected_hash:
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_physical_final_report_hash_invalid."
        )
    operation_root = final_report_path.parent
    return EtfMinsBootstrapSilverApplyReport(
        operation_id=str(payload["operation_id"]),
        plan_fingerprint=str(payload["plan_fingerprint"]),
        raw_final_report_hash=str(payload["raw_final_report_hash"]),
        raw_observation_summary_hash=str(payload["raw_observation_summary_hash"]),
        raw_decision_summary_hash=str(payload["raw_decision_summary_hash"]),
        finalized_raw_manifest_hash=str(payload["finalized_raw_manifest_hash"]),
        silver_work_manifest_path=(
            operation_root / str(payload["silver_work_manifest_relative_path"])
        ),
        silver_work_manifest_hash=str(payload["silver_work_manifest_hash"]),
        finalized_silver_manifest_path=(
            operation_root / str(payload["finalized_silver_manifest_relative_path"])
        ),
        finalized_silver_manifest_hash=str(payload["finalized_silver_manifest_hash"]),
        checkpoint_path=(
            operation_root / str(payload["silver_checkpoint_relative_path"])
        ),
        final_report_path=final_report_path,
        raw_file_count=int(payload["raw_file_count"]),
        raw_row_count=int(payload["raw_row_count"]),
        silver_file_count=int(payload["silver_file_count"]),
        silver_row_count=int(payload["silver_row_count"]),
        added_file_count=int(payload["added_file_count"]),
        reused_file_count=int(payload["reused_file_count"]),
        blocked_partition_count=int(payload["blocked_partition_count"]),
        warn_partition_count=int(payload["warn_partition_count"]),
        checkpoint_hash=str(payload["checkpoint_hash"]),
        report_hash=expected_hash,
    )


def _ensure_etf_mins_source_batch(
    *,
    connection: Any,
    operation_root: Path,
    plan: EtfMinsBootstrapPlan,
    prod_postgres: ProdPostgresResource,
    source_freq: str,
    trade_dates: Sequence[str],
) -> dict[str, object]:
    normalized_freq = normalize_etf_mins_source_freq(source_freq)
    normalized_dates = _normalize_trade_dates(trade_dates)
    scope_payload = _source_batch_scope_payload(
        plan=plan,
        source_freq=normalized_freq,
        trade_dates=normalized_dates,
    )
    batch_directory, source_path, receipt_path = _source_batch_paths(
        operation_root=operation_root,
        scope_payload=scope_payload,
    )
    scope_hash = compute_etf_mins_bootstrap_payload_hash(scope_payload)
    if source_path.exists() != receipt_path.exists():
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_source_batch_partial: source Parquet and receipt must "
            "either both exist or both be absent."
        )
    if source_path.exists():
        receipt = _load_json(receipt_path, label="ETF minute source batch receipt")
        _validate_source_receipt(
            receipt,
            source_path=source_path,
            expected_scope_hash=scope_hash,
            operation_root=operation_root,
        )
        connection.execute(
            f"CREATE TEMP VIEW {_SOURCE_BATCH_RELATION} AS "
            f"SELECT * FROM {read_parquet(source_path, hive_partitioning=False)}"
        )
        observed_stats = _source_batch_stats(
            connection,
            relation=_SOURCE_BATCH_RELATION,
            trade_dates=normalized_dates,
        )
        _assert_source_receipt_stats(receipt, observed_stats)
        return dict(receipt)

    if batch_directory.exists():
        if not batch_directory.is_dir() or any(batch_directory.iterdir()):
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_source_batch_partial: an incomplete source "
                "batch directory contains unrecognized content."
            )
    else:
        batch_directory.mkdir(parents=True, exist_ok=False)
    source_sql = build_prod_etf_mins_duckdb_source_sql(
        source_freq=normalized_freq,
        start_datetime=str(scope_payload["start_datetime"]),
        end_datetime=str(scope_payload["end_datetime"]),
    )
    _load_duckdb_postgres_extension(connection)
    _attach_prod_etf_mins_readonly(
        connection,
        postgres_connection_string=prod_postgres.duckdb_connection_string(),
    )
    started_at = perf_counter()
    try:
        connection.execute(
            f"CREATE TEMP TABLE {_SOURCE_BATCH_RELATION} AS {source_sql}"
        )
    except duckdb_module.Error:
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_detail_query_failed: the single bounded Prod query "
            "failed; connection details and SQL are omitted."
        ) from None
    try:
        connection.execute(
            copy_query_to_parquet(
                f"SELECT {_RAW_COLUMNS_SQL} FROM {_SOURCE_BATCH_RELATION} "
                "ORDER BY trade_time, ts_code",
                source_path,
            )
        )
    except duckdb_module.Error:
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_source_batch_write_failed: the bounded source "
            "relation could not be persisted."
        ) from None
    stats = _source_batch_stats(
        connection,
        relation=_SOURCE_BATCH_RELATION,
        trade_dates=normalized_dates,
    )
    receipt: dict[str, object] = {
        "batch_key": _batch_key(normalized_freq, normalized_dates),
        "source_query_scope_hash": scope_hash,
        "source_freq": normalized_freq,
        "trade_dates": list(normalized_dates),
        "source_relative_path": source_path.relative_to(operation_root).as_posix(),
        **stats,
        "source_file_sha256": _sha256_file(source_path),
        "source_file_size_bytes": source_path.stat().st_size,
        "source_query_count": 1,
        "batch_elapsed_ms": max(0, int((perf_counter() - started_at) * 1000)),
    }
    receipt["receipt_hash"] = compute_etf_mins_bootstrap_payload_hash(receipt)
    _write_immutable_json(receipt_path, receipt)
    return receipt


def _source_batch_scope_payload(
    *,
    plan: EtfMinsBootstrapPlan,
    source_freq: str,
    trade_dates: Sequence[str],
) -> dict[str, object]:
    normalized_freq = normalize_etf_mins_source_freq(source_freq)
    normalized_dates = _normalize_trade_dates(trade_dates)
    first_date = normalized_dates[0]
    last_date = normalized_dates[-1]
    return {
        "plan_fingerprint": plan.plan_fingerprint,
        "source_freq": normalized_freq,
        "trade_dates": list(normalized_dates),
        "start_datetime": f"{first_date} 00:00:00",
        "end_datetime": (
            f"{(date.fromisoformat(last_date) + timedelta(days=1)).isoformat()} "
            "00:00:00"
        ),
    }


def _source_batch_paths(
    *,
    operation_root: Path,
    scope_payload: Mapping[str, object],
) -> tuple[Path, Path, Path]:
    scope_hash = compute_etf_mins_bootstrap_payload_hash(scope_payload)
    batch_directory = (
        operation_root
        / "raw"
        / "source_batches"
        / f"freq={scope_payload['source_freq']}"
        / f"batch_id={scope_hash[:16]}"
    )
    return (
        batch_directory,
        batch_directory / "part-000.parquet",
        batch_directory / "source_receipt.json",
    )


def _batch_targets_are_completed(
    checkpoint: Mapping[str, object],
    *,
    source_freq: str,
    trade_dates: Sequence[str],
) -> bool:
    completed_targets = checkpoint.get("completed_targets")
    if not isinstance(completed_targets, Mapping):
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_checkpoint_shape_invalid: completed_targets."
        )
    return all(
        _target_key(source_freq, trade_date) in completed_targets
        for trade_date in trade_dates
    )


def _assert_completed_batch_targets_unchanged(
    *,
    checkpoint: Mapping[str, object],
    lake_root: Path,
    source_freq: str,
    trade_dates: Sequence[str],
) -> None:
    completed_targets = checkpoint.get("completed_targets")
    if not isinstance(completed_targets, Mapping):
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_checkpoint_shape_invalid: completed_targets."
        )
    normalized_freq = normalize_etf_mins_source_freq(source_freq)
    for trade_date in _normalize_trade_dates(trade_dates):
        normalized_date = normalize_etf_mins_trade_date(trade_date)
        record = completed_targets.get(_target_key(normalized_freq, normalized_date))
        target_path = raw_etf_mins_path(
            lake_root,
            normalized_freq,
            normalized_date,
        )
        expected_relative_path = target_path.relative_to(lake_root).as_posix()
        if (
            not isinstance(record, Mapping)
            or record.get("source_freq") != normalized_freq
            or record.get("trade_date") != normalized_date
            or record.get("formal_raw_relative_path") != expected_relative_path
            or record.get("disposition") not in {"added", "reused"}
            or not target_path.is_file()
            or record.get("formal_raw_sha256") != _sha256_file(target_path)
        ):
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_checkpoint_target_drift: a completed formal "
                "Raw file no longer matches its checkpoint."
            )


def _cleanup_completed_source_batch(
    *,
    operation_root: Path,
    plan: EtfMinsBootstrapPlan,
    source_freq: str,
    trade_dates: Sequence[str],
) -> None:
    scope_payload = _source_batch_scope_payload(
        plan=plan,
        source_freq=source_freq,
        trade_dates=trade_dates,
    )
    batch_directory, source_path, receipt_path = _source_batch_paths(
        operation_root=operation_root,
        scope_payload=scope_payload,
    )
    cleanup_directory = batch_directory.with_name(f".{batch_directory.name}.cleanup")
    if cleanup_directory.exists():
        _remove_completed_source_batch_directory(cleanup_directory)
    if not batch_directory.exists():
        return
    if not source_path.is_file() or not receipt_path.is_file():
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_source_batch_partial: completed batch staging is "
            "not a complete source Parquet/receipt pair."
        )
    receipt = _load_json(receipt_path, label="ETF minute source batch receipt")
    _validate_source_receipt(
        receipt,
        source_path=source_path,
        expected_scope_hash=compute_etf_mins_bootstrap_payload_hash(scope_payload),
        operation_root=operation_root,
    )
    os.replace(batch_directory, cleanup_directory)
    _remove_completed_source_batch_directory(cleanup_directory)
    for parent in (batch_directory.parent, batch_directory.parent.parent):
        try:
            parent.rmdir()
        except OSError:
            break


def _remove_completed_source_batch_directory(path: Path) -> None:
    if not path.is_dir():
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_source_batch_cleanup_invalid: expected a directory."
        )
    allowed_names = {"part-000.parquet", "source_receipt.json"}
    children = tuple(path.iterdir())
    if any(
        child.name not in allowed_names or not child.is_file() for child in children
    ):
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_source_batch_cleanup_invalid: cleanup directory "
            "contains unrecognized content."
        )
    for child in children:
        child.unlink()
    path.rmdir()


def _apply_one_etf_mins_raw_target(
    *,
    connection: Any,
    lake_root: Path,
    staging_root: Path,
    plan: EtfMinsBootstrapPlan,
    checkpoint: Mapping[str, object],
    source_freq: str,
    trade_date: str,
) -> dict[str, object]:
    normalized_freq = normalize_etf_mins_source_freq(source_freq)
    normalized_date = normalize_etf_mins_trade_date(trade_date)
    connection.execute(
        f"CREATE OR REPLACE TEMP VIEW {_SOURCE_DATE_RELATION} AS "
        f"SELECT {_RAW_COLUMNS_SQL} FROM {_SOURCE_BATCH_RELATION} "
        f"WHERE CAST(trade_time AS DATE) = DATE {duckdb_string(normalized_date)}"
    )
    candidate_path = etf_mins_staging_path(
        staging_root,
        plan.operation_id,
        "raw",
        normalized_freq,
        normalized_date,
    )
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    if not candidate_path.exists():
        connection.execute(
            copy_query_to_parquet(
                f"SELECT {_RAW_COLUMNS_SQL} FROM {_SOURCE_DATE_RELATION} "
                "ORDER BY ts_code, trade_time",
                candidate_path,
            )
        )
    try:
        connection.execute(
            f"CREATE OR REPLACE TEMP VIEW {_CANDIDATE_RELATION} AS "
            f"SELECT * FROM {read_parquet(candidate_path, hive_partitioning=False)}"
        )
    except Exception:  # noqa: BLE001 - normalize candidate readback failures.
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_candidate_unreadable: the run-scoped Raw candidate "
            "cannot be read."
        ) from None
    target_path = raw_etf_mins_path(lake_root, normalized_freq, normalized_date)
    existing_relation: str | None = None
    if target_path.exists():
        if not target_path.is_file():
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_target_conflict: formal Raw target is not a file."
            )
        try:
            connection.execute(
                f"CREATE OR REPLACE TEMP VIEW {_EXISTING_RELATION} AS "
                f"SELECT * FROM {read_parquet(target_path, hive_partitioning=False)}"
            )
        except Exception:  # noqa: BLE001 - unreadable formal targets are conflicts.
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_target_conflict: formal Raw target is unreadable."
            ) from None
        existing_relation = _EXISTING_RELATION
    validation = evaluate_etf_mins_raw_candidate(
        connection=connection,
        source_relation=_SOURCE_DATE_RELATION,
        candidate_relation=_CANDIDATE_RELATION,
        basic_all_relation=_BASIC_ALL_RELATION,
        requestable_targets_relation=_REQUESTABLE_RELATION,
        trade_date=normalized_date,
        source_freq=normalized_freq,
        existing_target_relation=existing_relation,
    )
    _assert_bootstrap_candidate_promotable(validation)
    candidate_sha256 = _sha256_file(candidate_path)
    candidate_size_bytes = candidate_path.stat().st_size
    completed_targets = checkpoint.get("completed_targets")
    checkpoint_record = (
        completed_targets.get(_target_key(normalized_freq, normalized_date))
        if isinstance(completed_targets, Mapping)
        else None
    )
    if checkpoint_record is not None:
        if not isinstance(checkpoint_record, Mapping) or existing_relation is None:
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_checkpoint_target_drift: a completed formal "
                "target is missing or its checkpoint record is invalid."
            )
        if not etf_mins_relations_are_semantically_equal(
            connection,
            left_relation=_CANDIDATE_RELATION,
            right_relation=existing_relation,
        ):
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_target_conflict: completed formal Raw content "
                "no longer matches the frozen source batch."
            )
        disposition = str(checkpoint_record.get("disposition"))
        if disposition not in {"added", "reused"}:
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_checkpoint_target_drift: invalid disposition."
            )
        candidate_path.unlink()
    elif existing_relation is not None:
        if not etf_mins_relations_are_semantically_equal(
            connection,
            left_relation=_CANDIDATE_RELATION,
            right_relation=existing_relation,
        ):
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_target_conflict: formal Raw differs from the "
                "validated candidate and will not be overwritten."
            )
        disposition = "reused"
        candidate_path.unlink()
    else:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists():
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_target_conflict: formal Raw appeared during "
                "promotion and will not be overwritten."
            )
        try:
            os.replace(candidate_path, target_path)
        except OSError:
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_atomic_promote_failed: candidate was not "
                "promoted to formal Raw."
            ) from None
        disposition = "added"
    if not target_path.is_file():
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_formal_target_missing: promotion did not leave a file."
        )
    formal_sha256 = _sha256_file(target_path)
    formal_size_bytes = target_path.stat().st_size
    return _raw_manifest_row(
        plan=plan,
        validation=validation,
        source_freq=normalized_freq,
        trade_date=normalized_date,
        target_path=target_path,
        lake_root=lake_root,
        staging_sha256=candidate_sha256,
        staging_size_bytes=candidate_size_bytes,
        formal_sha256=formal_sha256,
        formal_size_bytes=formal_size_bytes,
        disposition=disposition,
    )


def _raw_manifest_row(
    *,
    plan: EtfMinsBootstrapPlan,
    validation: EtfMinsRawCandidateValidation,
    source_freq: str,
    trade_date: str,
    target_path: Path,
    lake_root: Path,
    staging_sha256: str,
    staging_size_bytes: int,
    formal_sha256: str,
    formal_size_bytes: int,
    disposition: str,
) -> dict[str, object]:
    return {
        "operation_id": plan.operation_id,
        "plan_fingerprint": plan.plan_fingerprint,
        "source_freq": source_freq,
        "trade_date": trade_date,
        "formal_raw_relative_path": target_path.relative_to(lake_root).as_posix(),
        "source_row_count": validation.source_row_count,
        "source_code_count": validation.distinct_code_count,
        "staging_row_count": validation.candidate_row_count,
        "staging_sha256": staging_sha256,
        "staging_size_bytes": staging_size_bytes,
        "formal_raw_row_count": validation.candidate_row_count,
        "formal_raw_sha256": formal_sha256,
        "formal_raw_size_bytes": formal_size_bytes,
        "disposition": disposition,
        "zero_row": validation.candidate_row_count == 0,
        "expected_count": validation.expected_count,
        "present_count": validation.present_count,
        "missing_count": validation.missing_count,
        "known_non_required_present_count": (
            validation.known_non_required_present_count
        ),
        "retained_legacy_count": validation.retained_legacy_count,
        "unexplained_new_count": validation.unexplained_new_count,
        "grid_gap_candidate_count": validation.grid_gap_candidate_count,
        "policy_state": validation.policy_state,
        "silver_eligible": validation.silver_eligible,
    }


def _source_batch_stats(
    connection: Any,
    *,
    relation: str,
    trade_dates: Sequence[str],
) -> dict[str, object]:
    allowed_dates = ", ".join(
        f"DATE {duckdb_string(trade_date)}" for trade_date in trade_dates
    )
    row = connection.execute(
        f"""
        SELECT
          count(*) AS source_row_count,
          count(DISTINCT ts_code) AS source_code_count,
          min(trade_time) AS source_min_trade_time,
          max(trade_time) AS source_max_trade_time,
          count(*) FILTER (
            WHERE CAST(trade_time AS DATE) IN ({allowed_dates})
          ) AS source_assigned_row_count,
          count(*) FILTER (
            WHERE trade_time IS NULL
               OR CAST(trade_time AS DATE) NOT IN ({allowed_dates})
          ) AS unexpected_trade_date_count
        FROM {relation}
        """
    ).fetchone()
    if row is None:
        raise EtfMinsBootstrapError("etf_mins_bootstrap_source_stats_missing.")
    return {
        "source_row_count": int(row[0]),
        "source_code_count": int(row[1]),
        "source_min_trade_time": _datetime_text(row[2]),
        "source_max_trade_time": _datetime_text(row[3]),
        "source_assigned_row_count": int(row[4]),
        "unexpected_trade_date_count": int(row[5]),
    }


def _assert_bootstrap_candidate_promotable(
    validation: EtfMinsRawCandidateValidation,
) -> None:
    if validation.promotion_allowed:
        return
    raise EtfMinsBootstrapError(
        "etf_mins_bootstrap_candidate_rejected: "
        f"reason_codes={validation.stable_blocking_reason_codes}, "
        f"unexplained_new_samples={validation.unexplained_new_samples}."
    )


def _write_or_validate_finalized_raw_manifest(
    *,
    path: Path,
    rows: Sequence[Mapping[str, object]],
    expected_hash: str,
    duckdb: DuckDBResource,
) -> None:
    if path.exists():
        observed_rows = _load_finalized_raw_manifest(path=path, duckdb=duckdb)
        observed_hash = compute_etf_mins_bootstrap_manifest_hash(
            observed_rows,
            key_fields=("source_freq", "trade_date"),
        )
        if observed_hash != expected_hash:
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_finalized_manifest_conflict: existing manifest "
                "differs from the completed checkpoint."
            )
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path = path.with_name(f".{path.name}.candidate-{uuid.uuid4().hex}")
    columns = _FINALIZED_RAW_MANIFEST_COLUMNS
    if any(set(row) != set(columns) for row in rows):
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_finalized_manifest_row_schema_invalid."
        )
    schema_sql = ", ".join(
        f"{column} {_FINALIZED_RAW_MANIFEST_TYPES[column]}" for column in columns
    )
    placeholders = ", ".join("?" for _ in columns)
    try:
        with duckdb.connect() as connection:
            connection.execute(
                f"CREATE TEMP TABLE finalized_raw_manifest ({schema_sql})"
            )
            if rows:
                connection.executemany(
                    f"INSERT INTO finalized_raw_manifest VALUES ({placeholders})",
                    [tuple(row[column] for column in columns) for row in rows],
                )
            connection.execute(
                copy_query_to_parquet(
                    "SELECT * FROM finalized_raw_manifest "
                    "ORDER BY source_freq, trade_date",
                    candidate_path,
                )
            )
        os.replace(candidate_path, path)
    except Exception:
        if candidate_path.exists():
            candidate_path.unlink()
        raise
    observed_rows = _load_finalized_raw_manifest(path=path, duckdb=duckdb)
    observed_hash = compute_etf_mins_bootstrap_manifest_hash(
        observed_rows,
        key_fields=("source_freq", "trade_date"),
    )
    if observed_hash != expected_hash:
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_finalized_manifest_hash_mismatch."
        )


_FINALIZED_RAW_MANIFEST_COLUMNS = (
    "operation_id",
    "plan_fingerprint",
    "source_freq",
    "trade_date",
    "formal_raw_relative_path",
    "source_row_count",
    "source_code_count",
    "staging_row_count",
    "staging_sha256",
    "staging_size_bytes",
    "formal_raw_row_count",
    "formal_raw_sha256",
    "formal_raw_size_bytes",
    "disposition",
    "zero_row",
    "expected_count",
    "present_count",
    "missing_count",
    "known_non_required_present_count",
    "retained_legacy_count",
    "unexplained_new_count",
    "grid_gap_candidate_count",
    "policy_state",
    "silver_eligible",
)
_FINALIZED_RAW_MANIFEST_TYPES = {
    column: (
        "BOOLEAN"
        if column in {"zero_row", "silver_eligible"}
        else "BIGINT"
        if column.endswith(("_count", "_bytes"))
        else "VARCHAR"
    )
    for column in _FINALIZED_RAW_MANIFEST_COLUMNS
}


def _load_finalized_raw_manifest(
    *,
    path: Path,
    duckdb: DuckDBResource,
) -> tuple[dict[str, object], ...]:
    try:
        with duckdb.connect() as connection:
            cursor = connection.execute(
                f"SELECT * FROM {read_parquet(path, hive_partitioning=False)} "
                "ORDER BY source_freq, trade_date"
            )
            columns = tuple(str(item[0]) for item in cursor.description)
            if columns != _FINALIZED_RAW_MANIFEST_COLUMNS:
                raise EtfMinsBootstrapError(
                    "etf_mins_bootstrap_finalized_manifest_schema_invalid."
                )
            return tuple(
                dict(zip(columns, row, strict=True)) for row in cursor.fetchall()
            )
    except EtfMinsBootstrapError:
        raise
    except Exception:  # noqa: BLE001 - normalize manifest read failures.
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_finalized_manifest_unreadable."
        ) from None


def _load_completed_raw_apply_report(
    *,
    plan: EtfMinsBootstrapPlan,
    plan_path: Path,
    lake_root: Path,
    duckdb: DuckDBResource,
    finalized_manifest_path: Path,
    raw_final_report_path: Path,
    checkpoint_path: Path,
) -> EtfMinsBootstrapRawApplyReport:
    payload = _load_json(raw_final_report_path, label="ETF minute Raw final report")
    if payload.get("bootstrap_kind") != ETF_MINS_BOOTSTRAP_KIND:
        raise EtfMinsBootstrapError("etf_mins_bootstrap_raw_report_kind_invalid.")
    if int(payload.get("schema_version", 0)) != ETF_MINS_BOOTSTRAP_SCHEMA_VERSION:
        raise EtfMinsBootstrapError("etf_mins_bootstrap_raw_report_schema_invalid.")
    if payload.get("operation_id") != plan.operation_id:
        raise EtfMinsBootstrapError("etf_mins_bootstrap_raw_report_operation_mismatch.")
    if payload.get("plan_fingerprint") != plan.plan_fingerprint:
        raise EtfMinsBootstrapError("etf_mins_bootstrap_raw_report_plan_mismatch.")
    if payload.get("historical_protection_mode") != plan.historical_protection_mode:
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_raw_report_protection_mode_mismatch."
        )
    if (
        payload.get("protected_file_manifest_hash_before")
        != plan.protected_file_manifest_hash
        or payload.get("protected_file_manifest_hash_after")
        != plan.protected_file_manifest_hash
    ):
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_raw_report_protection_hash_mismatch."
        )
    if payload.get("report_hash") != compute_etf_mins_bootstrap_payload_hash(
        payload,
        self_hash_field="report_hash",
    ):
        raise EtfMinsBootstrapError("etf_mins_bootstrap_raw_report_hash_invalid.")
    operation_root = raw_final_report_path.parent.resolve(strict=False)
    expected_plan_relative_path = (
        plan_path.resolve(strict=False).relative_to(operation_root).as_posix()
    )
    if payload.get("plan_relative_path") != expected_plan_relative_path:
        raise EtfMinsBootstrapError("etf_mins_bootstrap_raw_report_plan_path_mismatch.")
    expected_checkpoint_relative_path = (
        checkpoint_path.resolve(strict=False).relative_to(operation_root).as_posix()
    )
    if payload.get("checkpoint_relative_path") != expected_checkpoint_relative_path:
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_raw_report_checkpoint_path_mismatch."
        )
    if payload.get("finalized_raw_manifest_relative_path") != (
        finalized_manifest_path.name
    ):
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_raw_report_manifest_path_invalid."
        )
    manifest_rows = _load_finalized_raw_manifest(
        path=finalized_manifest_path,
        duckdb=duckdb,
    )
    observed_manifest_hash = compute_etf_mins_bootstrap_manifest_hash(
        manifest_rows,
        key_fields=("source_freq", "trade_date"),
    )
    if observed_manifest_hash != payload.get("finalized_raw_manifest_hash"):
        raise EtfMinsBootstrapError("etf_mins_bootstrap_raw_report_manifest_mismatch.")
    _assert_finalized_raw_files(
        plan=plan,
        lake_root=lake_root,
        manifest_rows=manifest_rows,
    )
    checkpoint = _load_json(checkpoint_path, label="ETF minute Raw checkpoint")
    if _checkpoint_hash(checkpoint) != payload.get("checkpoint_hash"):
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_raw_report_checkpoint_mismatch."
        )
    return _raw_apply_report_from_payload(payload, raw_final_report_path)


def _assert_finalized_raw_files(
    *,
    plan: EtfMinsBootstrapPlan,
    lake_root: Path,
    manifest_rows: Sequence[Mapping[str, object]],
) -> None:
    expected_keys = {
        (source_freq, trade_date)
        for source_freq in plan.frequencies
        for trade_date in plan.expected_trade_dates
    }
    observed_keys: set[tuple[str, str]] = set()
    for row in manifest_rows:
        source_freq = normalize_etf_mins_source_freq(row["source_freq"])
        trade_date = normalize_etf_mins_trade_date(row["trade_date"])
        observed_keys.add((source_freq, trade_date))
        expected_path = raw_etf_mins_path(lake_root, source_freq, trade_date)
        relative_path = str(row["formal_raw_relative_path"])
        if relative_path != expected_path.relative_to(lake_root).as_posix():
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_finalized_raw_path_mismatch."
            )
        if not expected_path.is_file() or _sha256_file(expected_path) != row.get(
            "formal_raw_sha256"
        ):
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_finalized_raw_file_changed."
            )
    if observed_keys != expected_keys:
        raise EtfMinsBootstrapError("etf_mins_bootstrap_finalized_raw_scope_mismatch.")


def _assert_finalized_raw_evidence_closed(
    *,
    plan: EtfMinsBootstrapPlan,
    report: EtfMinsBootstrapRawApplyReport,
    manifest_rows: Sequence[Mapping[str, object]],
) -> None:
    if len(manifest_rows) != plan.target_file_count:
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_finalized_raw_file_count_mismatch."
        )
    for row in manifest_rows:
        if (
            row.get("operation_id") != plan.operation_id
            or row.get("plan_fingerprint") != plan.plan_fingerprint
        ):
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_finalized_raw_identity_mismatch."
            )
        if row.get("disposition") not in {"added", "reused"}:
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_finalized_raw_disposition_invalid."
            )
        if (
            row.get("policy_state") != "unclassified"
            or row.get("silver_eligible") is not False
        ):
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_finalized_raw_policy_invalid."
            )
        numeric_fields = (
            "source_row_count",
            "source_code_count",
            "staging_row_count",
            "staging_size_bytes",
            "formal_raw_row_count",
            "formal_raw_size_bytes",
            "expected_count",
            "present_count",
            "missing_count",
            "known_non_required_present_count",
            "retained_legacy_count",
            "unexplained_new_count",
            "grid_gap_candidate_count",
        )
        if any(int(row[field]) < 0 for field in numeric_fields):
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_finalized_raw_count_invalid."
            )
        if not (
            int(row["source_row_count"])
            == int(row["staging_row_count"])
            == int(row["formal_raw_row_count"])
        ):
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_finalized_raw_row_count_mismatch."
            )
        if int(row["source_code_count"]) != int(row["present_count"]):
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_finalized_raw_code_count_mismatch."
            )
        if bool(row["zero_row"]) != (int(row["formal_raw_row_count"]) == 0):
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_finalized_raw_zero_row_invalid."
            )
        if int(row["missing_count"]) > int(row["expected_count"]):
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_finalized_raw_coverage_invalid."
            )
    if (
        report.source_row_count
        != sum(int(row["source_row_count"]) for row in manifest_rows)
        or report.staging_row_count
        != sum(int(row["staging_row_count"]) for row in manifest_rows)
        or report.formal_raw_row_count
        != sum(int(row["formal_raw_row_count"]) for row in manifest_rows)
    ):
        raise EtfMinsBootstrapError("etf_mins_bootstrap_raw_report_row_count_mismatch.")
    if (
        report.added_file_count
        != sum(row["disposition"] == "added" for row in manifest_rows)
        or report.reused_file_count
        != sum(row["disposition"] == "reused" for row in manifest_rows)
        or report.zero_row_file_count
        != sum(bool(row["zero_row"]) for row in manifest_rows)
    ):
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_raw_report_file_count_mismatch."
        )
    if report.actual_remote_query_count != plan.raw_detail_query_count:
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_raw_report_query_count_mismatch."
        )


def _raw_apply_report_from_payload(
    payload: Mapping[str, object],
    raw_final_report_path: Path,
) -> EtfMinsBootstrapRawApplyReport:
    operation_root = raw_final_report_path.parent.resolve(strict=False)
    return EtfMinsBootstrapRawApplyReport(
        operation_id=str(payload["operation_id"]),
        plan_fingerprint=str(payload["plan_fingerprint"]),
        plan_path=_resolve_operation_report_artifact(
            operation_root=operation_root,
            relative_path=payload["plan_relative_path"],
            field_name="plan_relative_path",
        ),
        checkpoint_path=_resolve_operation_report_artifact(
            operation_root=operation_root,
            relative_path=payload["checkpoint_relative_path"],
            field_name="checkpoint_relative_path",
        ),
        finalized_raw_manifest_path=_resolve_operation_report_artifact(
            operation_root=operation_root,
            relative_path=payload["finalized_raw_manifest_relative_path"],
            field_name="finalized_raw_manifest_relative_path",
        ),
        finalized_raw_manifest_hash=str(payload["finalized_raw_manifest_hash"]),
        raw_final_report_path=raw_final_report_path,
        source_row_count=int(payload["source_row_count"]),
        staging_row_count=int(payload["staging_row_count"]),
        formal_raw_row_count=int(payload["formal_raw_row_count"]),
        added_file_count=int(payload["added_file_count"]),
        reused_file_count=int(payload["reused_file_count"]),
        zero_row_file_count=int(payload["zero_row_file_count"]),
        actual_remote_query_count=int(payload["actual_remote_query_count"]),
        temporary_space_peak_bytes=int(payload["temporary_space_peak_bytes"]),
        final_space_increment_bytes=int(payload["final_space_increment_bytes"]),
        checkpoint_hash=str(payload["checkpoint_hash"]),
        report_hash=str(payload["report_hash"]),
    )


def _resolve_operation_report_artifact(
    *,
    operation_root: Path,
    relative_path: object,
    field_name: str,
) -> Path:
    candidate_relative_path = Path(str(relative_path))
    if candidate_relative_path.is_absolute():
        raise EtfMinsBootstrapError(
            f"etf_mins_bootstrap_raw_report_{field_name}_invalid."
        )
    candidate_path = (operation_root / candidate_relative_path).resolve(strict=False)
    if candidate_path == operation_root or not candidate_path.is_relative_to(
        operation_root
    ):
        raise EtfMinsBootstrapError(
            f"etf_mins_bootstrap_raw_report_{field_name}_invalid."
        )
    return candidate_path


def _plan_from_payload(payload: Mapping[str, object]) -> EtfMinsBootstrapPlan:
    if payload.get("bootstrap_kind") != ETF_MINS_BOOTSTRAP_KIND:
        raise EtfMinsBootstrapError("etf_mins_bootstrap_plan_kind_invalid.")
    if int(payload.get("schema_version", 0)) != ETF_MINS_BOOTSTRAP_SCHEMA_VERSION:
        raise EtfMinsBootstrapError("etf_mins_bootstrap_plan_schema_invalid.")
    observed_fingerprint = str(payload.get("plan_fingerprint") or "")
    expected_fingerprint = compute_etf_mins_bootstrap_payload_hash(
        payload,
        self_hash_field="plan_fingerprint",
    )
    if observed_fingerprint != expected_fingerprint:
        raise EtfMinsBootstrapError("etf_mins_bootstrap_plan_fingerprint_invalid.")
    expected_trade_dates = _normalize_trade_dates(
        _string_sequence(payload.get("expected_trade_dates"), "expected_trade_dates")
    )
    frequencies = tuple(
        normalize_etf_mins_source_freq(value)
        for value in _string_sequence(payload.get("frequencies"), "frequencies")
    )
    if frequencies != ETF_MINS_SOURCE_FREQS:
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_plan_frequencies_invalid: all five source frequencies "
            "must be frozen in contract order."
        )
    expected_dates_hash = compute_etf_mins_bootstrap_payload_hash(
        {"trade_dates": list(expected_trade_dates)}
    )
    if payload.get("expected_trade_dates_hash") != expected_dates_hash:
        raise EtfMinsBootstrapError("etf_mins_bootstrap_trade_dates_hash_invalid.")
    frequencies_hash = compute_etf_mins_bootstrap_payload_hash(
        {"frequencies": list(frequencies)}
    )
    if payload.get("frequencies_hash") != frequencies_hash:
        raise EtfMinsBootstrapError("etf_mins_bootstrap_frequencies_hash_invalid.")
    target_file_count = int(payload.get("target_file_count", -1))
    if target_file_count != len(expected_trade_dates) * len(frequencies):
        raise EtfMinsBootstrapError("etf_mins_bootstrap_target_file_count_invalid.")
    raw_detail_query_count = int(payload.get("raw_detail_query_count", -1))
    expected_detail_query_count = len(frequencies) * math.ceil(
        len(expected_trade_dates) / ETF_MINS_BOOTSTRAP_BATCH_TRADE_DAY_LIMIT
    )
    if raw_detail_query_count != expected_detail_query_count:
        raise EtfMinsBootstrapError("etf_mins_bootstrap_detail_query_budget_invalid.")
    if int(payload.get("plan_coverage_query_count", -1)) != 1:
        raise EtfMinsBootstrapError("etf_mins_bootstrap_coverage_query_budget_invalid.")
    if int(payload.get("expected_remote_query_count", -1)) != (
        1 + raw_detail_query_count
    ):
        raise EtfMinsBootstrapError("etf_mins_bootstrap_remote_query_budget_invalid.")

    target_manifest_value = payload.get("preexisting_target_manifest")
    if not isinstance(target_manifest_value, list) or not all(
        isinstance(row, Mapping) for row in target_manifest_value
    ):
        raise EtfMinsBootstrapError("etf_mins_bootstrap_target_manifest_invalid.")
    target_manifest = tuple(dict(row) for row in target_manifest_value)
    if any(
        str(row.get("state")) not in ETF_MINS_BOOTSTRAP_TARGET_STATES
        for row in target_manifest
    ):
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_target_state_invalid: plan cannot pre-classify "
            "reused or conflict dispositions."
        )
    target_manifest_hash = compute_etf_mins_bootstrap_manifest_hash(
        target_manifest,
        key_fields=("source_freq", "trade_date"),
    )
    if payload.get("preexisting_target_manifest_hash") != target_manifest_hash:
        raise EtfMinsBootstrapError("etf_mins_bootstrap_target_manifest_hash_invalid.")
    protected_value = payload.get("protected_file_manifest")
    if not isinstance(protected_value, list) or not all(
        isinstance(row, Mapping) for row in protected_value
    ):
        raise EtfMinsBootstrapError("etf_mins_bootstrap_protected_manifest_invalid.")
    protected_manifest = tuple(dict(row) for row in protected_value)
    protection_mode = str(payload.get("historical_protection_mode") or "")
    protected_hash_value = payload.get("protected_file_manifest_hash")
    if protection_mode == ETF_MINS_BOOTSTRAP_PROTECTION_NOT_APPLICABLE:
        if protected_manifest or protected_hash_value is not None:
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_protection_contract_invalid: a 2026 plan must "
                "use not_applicable/null."
            )
    elif protection_mode == ETF_MINS_BOOTSTRAP_PROTECTION_2026:
        expected_protected_hash = compute_etf_mins_bootstrap_manifest_hash(
            protected_manifest,
            key_fields=("source_freq", "trade_date", "relative_path"),
        )
        if protected_hash_value != expected_protected_hash:
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_protected_manifest_hash_invalid."
            )
    else:
        raise EtfMinsBootstrapError("etf_mins_bootstrap_protection_mode_invalid.")

    stop_reasons = _string_sequence(payload.get("stop_reasons"), "stop_reasons")
    should_stop = bool(payload.get("should_stop"))
    if should_stop != bool(stop_reasons):
        raise EtfMinsBootstrapError("etf_mins_bootstrap_stop_state_invalid.")
    return EtfMinsBootstrapPlan(
        operation_id=_normalize_operation_id(payload.get("operation_id")),
        schema_version=ETF_MINS_BOOTSTRAP_SCHEMA_VERSION,
        created_at=str(payload["created_at"]),
        requested_start_date=normalize_etf_mins_trade_date(
            payload["requested_start_date"]
        ),
        requested_end_date=normalize_etf_mins_trade_date(payload["requested_end_date"]),
        execution_watermark_date=normalize_etf_mins_trade_date(
            payload["execution_watermark_date"]
        ),
        execution_watermark_coverage_fingerprint=str(
            payload["execution_watermark_coverage_fingerprint"]
        ),
        expected_trade_dates=expected_trade_dates,
        expected_trade_dates_hash=expected_dates_hash,
        trimmed_trade_dates=_normalize_trade_dates(
            _string_sequence(payload.get("trimmed_trade_dates"), "trimmed_trade_dates")
        ),
        frequencies=frequencies,
        frequencies_hash=frequencies_hash,
        plan_coverage_query_count=1,
        raw_detail_query_count=raw_detail_query_count,
        expected_remote_query_count=1 + raw_detail_query_count,
        basic_raw_snapshot_hash=str(payload["basic_raw_snapshot_hash"]),
        basic_silver_content_hash=str(payload["basic_silver_content_hash"]),
        basic_raw_observed_at=str(payload["basic_raw_observed_at"]),
        basic_silver_observed_at=str(payload["basic_silver_observed_at"]),
        eligibility_as_of=str(payload["eligibility_as_of"]),
        requestable_code_count=int(payload["requestable_code_count"]),
        requestable_code_hash=str(payload["requestable_code_hash"]),
        target_file_count=target_file_count,
        estimated_source_rows=int(payload["estimated_source_rows"]),
        estimate_basis=str(payload["estimate_basis"]),
        estimated_staging_bytes=int(payload["estimated_staging_bytes"]),
        estimated_final_increment_bytes=int(payload["estimated_final_increment_bytes"]),
        free_bytes=int(payload["free_bytes"]),
        required_free_bytes=int(payload["required_free_bytes"]),
        preexisting_target_state_summary=_int_mapping(
            payload.get("preexisting_target_state_summary"),
            "preexisting_target_state_summary",
        ),
        preexisting_target_manifest=target_manifest,
        preexisting_target_manifest_hash=target_manifest_hash,
        preexisting_silver_state_summary=_int_mapping(
            payload.get("preexisting_silver_state_summary"),
            "preexisting_silver_state_summary",
        ),
        historical_protection_mode=protection_mode,
        protected_file_manifest=protected_manifest,
        protected_file_manifest_hash=(
            None if protected_hash_value is None else str(protected_hash_value)
        ),
        should_stop=should_stop,
        stop_reasons=stop_reasons,
        plan_fingerprint=observed_fingerprint,
    )


def _build_historical_protection_contract(
    *,
    lake_root: Path,
    requested_start_date: str,
    requested_end_date: str,
    protect_from_date: str | None,
) -> tuple[str, tuple[Mapping[str, object], ...], str | None]:
    cutoff = ETF_MINS_HISTORICAL_PROTECTION_CUTOFF.isoformat()
    if protect_from_date is None:
        if requested_start_date < cutoff:
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_protection_required: pre-2026 plans must protect "
                "all 2026 and later Raw files."
            )
        return ETF_MINS_BOOTSTRAP_PROTECTION_NOT_APPLICABLE, (), None
    normalized_protect_from = normalize_etf_mins_trade_date(protect_from_date)
    if normalized_protect_from != cutoff:
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_protect_from_date_invalid: only 2026-01-01 is allowed."
        )
    if requested_end_date >= cutoff:
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_protected_range_overlap: a protected historical plan "
            "must end on or before 2025-12-31."
        )
    manifest = _collect_protected_raw_manifest(
        lake_root=lake_root,
        protect_from_date=cutoff,
    )
    manifest_hash = compute_etf_mins_bootstrap_manifest_hash(
        manifest,
        key_fields=("source_freq", "trade_date", "relative_path"),
    )
    return ETF_MINS_BOOTSTRAP_PROTECTION_2026, manifest, manifest_hash


def _collect_protected_raw_manifest(
    *,
    lake_root: Path,
    protect_from_date: str,
) -> tuple[Mapping[str, object], ...]:
    dataset_root = lake_root / "raw" / "tushare" / "etf_mins"
    rows: list[dict[str, object]] = []
    if not dataset_root.exists():
        return ()
    for path in sorted(dataset_root.glob("freq=*/trade_date=*/part-000.parquet")):
        source_freq = normalize_etf_mins_source_freq(
            path.parents[1].name.split("=", 1)[1]
        )
        trade_date = normalize_etf_mins_trade_date(path.parent.name.split("=", 1)[1])
        if trade_date < protect_from_date:
            continue
        if not path.is_file():
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_protected_file_invalid: protected target is not "
                "a regular file."
            )
        rows.append(
            {
                "source_freq": source_freq,
                "trade_date": trade_date,
                "relative_path": path.relative_to(lake_root).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    return tuple(rows)


def _assert_protected_manifest_unchanged(
    *,
    plan: EtfMinsBootstrapPlan,
    lake_root: Path,
) -> None:
    if plan.historical_protection_mode == (
        ETF_MINS_BOOTSTRAP_PROTECTION_NOT_APPLICABLE
    ):
        if plan.protected_file_manifest_hash is not None:
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_protection_contract_invalid."
            )
        return
    current_manifest = _collect_protected_raw_manifest(
        lake_root=lake_root,
        protect_from_date=ETF_MINS_HISTORICAL_PROTECTION_CUTOFF.isoformat(),
    )
    current_hash = compute_etf_mins_bootstrap_manifest_hash(
        current_manifest,
        key_fields=("source_freq", "trade_date", "relative_path"),
    )
    if current_hash != plan.protected_file_manifest_hash:
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_protected_files_changed: 2026 and later Raw files "
            "differ from the frozen protection manifest."
        )


def _normalize_watermark_coverages(
    coverages: Sequence[ProdEtfMinsFrequencyCoverage],
    *,
    expected_trade_dates: Sequence[str],
) -> tuple[ProdEtfMinsFrequencyCoverage, ...]:
    expected_dates = set(expected_trade_dates)
    normalized = tuple(
        sorted(
            coverages,
            key=lambda coverage: (
                coverage.trade_date,
                ETF_MINS_SOURCE_FREQS.index(coverage.source_freq),
            ),
        )
    )
    keys = [(coverage.trade_date, coverage.source_freq) for coverage in normalized]
    if len(keys) != len(set(keys)):
        raise EtfMinsBootstrapError("etf_mins_bootstrap_watermark_coverage_duplicate.")
    if any(coverage.trade_date not in expected_dates for coverage in normalized):
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_watermark_coverage_scope_invalid."
        )
    return normalized


def _latest_complete_watermark(
    candidate_dates: Sequence[str],
    coverages: Sequence[ProdEtfMinsFrequencyCoverage],
) -> str | None:
    by_key = {
        (coverage.trade_date, coverage.source_freq): coverage for coverage in coverages
    }
    for trade_date in reversed(candidate_dates):
        rows = tuple(
            by_key.get((trade_date, source_freq))
            for source_freq in ETF_MINS_SOURCE_FREQS
        )
        if all(row is not None and row.ready for row in rows):
            return trade_date
    return None


def _basic_reference_from_plan(
    plan: EtfMinsBootstrapPlan,
    *,
    lake_root: Path,
) -> EtfBasicSilverSnapshotReference:
    return build_etf_basic_silver_snapshot_reference(
        raw_snapshot_hash=plan.basic_raw_snapshot_hash,
        silver_content_hash=plan.basic_silver_content_hash,
        raw_uri=str(
            raw_etf_basic_snapshot_path(lake_root, plan.basic_raw_snapshot_hash)
        ),
        silver_uri=str(
            silver_etf_basic_snapshot_path(lake_root, plan.basic_raw_snapshot_hash)
        ),
        raw_observed_at=plan.basic_raw_observed_at,
        silver_observed_at=plan.basic_silver_observed_at,
        eligibility_as_of=plan.eligibility_as_of,
        requestable_code_count=plan.requestable_code_count,
        requestable_code_hash=plan.requestable_code_hash,
    )


def _load_or_initialize_checkpoint(
    *,
    checkpoint_path: Path,
    plan: EtfMinsBootstrapPlan,
) -> dict[str, object]:
    if checkpoint_path.exists():
        payload = _load_json(checkpoint_path, label="ETF minute Raw checkpoint")
        if payload.get("operation_id") != plan.operation_id:
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_checkpoint_operation_mismatch."
            )
        if payload.get("plan_fingerprint") != plan.plan_fingerprint:
            raise EtfMinsBootstrapError("etf_mins_bootstrap_checkpoint_plan_mismatch.")
        if payload.get("checkpoint_hash") != _checkpoint_hash(payload):
            raise EtfMinsBootstrapError("etf_mins_bootstrap_checkpoint_hash_invalid.")
        if not isinstance(payload.get("source_batches"), dict) or not isinstance(
            payload.get("completed_targets"), dict
        ):
            raise EtfMinsBootstrapError("etf_mins_bootstrap_checkpoint_shape_invalid.")
        return payload
    payload = {
        "bootstrap_kind": ETF_MINS_BOOTSTRAP_KIND,
        "schema_version": ETF_MINS_BOOTSTRAP_SCHEMA_VERSION,
        "operation_id": plan.operation_id,
        "plan_fingerprint": plan.plan_fingerprint,
        "source_batches": {},
        "completed_targets": {},
    }
    _write_checkpoint(checkpoint_path, payload)
    return payload


def _merge_source_receipt_into_checkpoint(
    checkpoint: dict[str, object],
    *,
    receipt: Mapping[str, object],
) -> None:
    source_batches = checkpoint.get("source_batches")
    if not isinstance(source_batches, dict):
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_checkpoint_shape_invalid: source_batches."
        )
    batch_key = str(receipt["batch_key"])
    existing = source_batches.get(batch_key)
    if existing is not None:
        if not isinstance(existing, Mapping) or any(
            existing.get(field) != value for field, value in receipt.items()
        ):
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_source_receipt_conflict: checkpoint and source "
                "receipt differ."
            )
        return
    source_batches[batch_key] = dict(receipt)


def _update_source_batch_summary(
    checkpoint: dict[str, object],
    *,
    source_freq: str,
    trade_dates: Sequence[str],
) -> None:
    normalized_freq = normalize_etf_mins_source_freq(source_freq)
    normalized_dates = _normalize_trade_dates(trade_dates)
    source_batches = checkpoint.get("source_batches")
    completed_targets = checkpoint.get("completed_targets")
    if not isinstance(source_batches, dict) or not isinstance(
        completed_targets,
        Mapping,
    ):
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_checkpoint_shape_invalid: batch summary."
        )
    batch_key = _batch_key(normalized_freq, normalized_dates)
    batch_record = source_batches.get(batch_key)
    if not isinstance(batch_record, dict):
        raise EtfMinsBootstrapError("etf_mins_bootstrap_source_batch_summary_missing.")
    target_records = tuple(
        completed_targets.get(_target_key(normalized_freq, trade_date))
        for trade_date in normalized_dates
    )
    if any(
        record is not None and not isinstance(record, Mapping)
        for record in target_records
    ):
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_checkpoint_target_drift: invalid batch target."
        )
    completed_records = tuple(
        record for record in target_records if isinstance(record, Mapping)
    )
    batch_record.update(
        {
            "staging_row_count": sum(
                int(record["staging_row_count"]) for record in completed_records
            ),
            "formal_raw_row_count": sum(
                int(record["formal_raw_row_count"]) for record in completed_records
            ),
            "promoted_file_count": sum(
                str(record["disposition"]) == "added" for record in completed_records
            ),
            "reused_file_count": sum(
                str(record["disposition"]) == "reused" for record in completed_records
            ),
            "zero_row_file_count": sum(
                bool(record["zero_row"]) for record in completed_records
            ),
            "temporary_space_peak_bytes": int(batch_record["source_file_size_bytes"])
            + max(
                (int(record["staging_size_bytes"]) for record in completed_records),
                default=0,
            ),
            "completed_target_count": len(completed_records),
            "batch_completed": len(completed_records) == len(normalized_dates),
        }
    )


def _assert_source_batch_summaries_closed(
    checkpoint: dict[str, object],
    *,
    frequencies: Sequence[str],
    date_batches: Sequence[Sequence[str]],
) -> None:
    source_batches = checkpoint.get("source_batches")
    if not isinstance(source_batches, Mapping):
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_checkpoint_shape_invalid: source_batches."
        )
    expected_batch_keys = {
        _batch_key(source_freq, trade_dates)
        for source_freq in frequencies
        for trade_dates in date_batches
    }
    if set(source_batches) != expected_batch_keys:
        raise EtfMinsBootstrapError("etf_mins_bootstrap_source_batch_scope_mismatch.")
    for source_freq in frequencies:
        for trade_dates in date_batches:
            _update_source_batch_summary(
                checkpoint,
                source_freq=source_freq,
                trade_dates=trade_dates,
            )
            batch_record = source_batches[_batch_key(source_freq, trade_dates)]
            if not isinstance(batch_record, Mapping) or not bool(
                batch_record.get("batch_completed")
            ):
                raise EtfMinsBootstrapError(
                    "etf_mins_bootstrap_source_batch_incomplete."
                )


def _write_checkpoint(path: Path, checkpoint: dict[str, object]) -> None:
    checkpoint["checkpoint_hash"] = _checkpoint_hash(checkpoint)
    _atomic_write_json(path, checkpoint)


def _checkpoint_hash(checkpoint: Mapping[str, object]) -> str:
    return compute_etf_mins_bootstrap_payload_hash(
        checkpoint,
        self_hash_field="checkpoint_hash",
    )


def _actual_remote_query_count(checkpoint: Mapping[str, object]) -> int:
    source_batches = checkpoint.get("source_batches")
    if not isinstance(source_batches, Mapping):
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_checkpoint_shape_invalid: source_batches."
        )
    return sum(
        int(receipt.get("source_query_count", 0))
        for receipt in source_batches.values()
        if isinstance(receipt, Mapping)
    )


def _validate_source_receipt(
    receipt: Mapping[str, object],
    *,
    source_path: Path,
    expected_scope_hash: str,
    operation_root: Path,
) -> None:
    if receipt.get("receipt_hash") != compute_etf_mins_bootstrap_payload_hash(
        receipt,
        self_hash_field="receipt_hash",
    ):
        raise EtfMinsBootstrapError("etf_mins_bootstrap_source_receipt_hash_invalid.")
    if receipt.get("source_query_scope_hash") != expected_scope_hash:
        raise EtfMinsBootstrapError("etf_mins_bootstrap_source_scope_hash_mismatch.")
    if int(receipt.get("source_query_count", 0)) != 1:
        raise EtfMinsBootstrapError("etf_mins_bootstrap_source_query_count_invalid.")
    expected_relative = source_path.relative_to(operation_root).as_posix()
    if receipt.get("source_relative_path") != expected_relative:
        raise EtfMinsBootstrapError("etf_mins_bootstrap_source_receipt_path_mismatch.")
    if receipt.get("source_file_sha256") != _sha256_file(source_path):
        raise EtfMinsBootstrapError("etf_mins_bootstrap_source_file_hash_mismatch.")
    if int(receipt.get("source_file_size_bytes", -1)) != source_path.stat().st_size:
        raise EtfMinsBootstrapError("etf_mins_bootstrap_source_file_size_mismatch.")


def _assert_source_receipt_stats(
    receipt: Mapping[str, object],
    observed_stats: Mapping[str, object],
) -> None:
    for field, observed in observed_stats.items():
        if receipt.get(field) != observed:
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_source_receipt_stats_mismatch: " + field
            )


def _read_parquet_paths(paths: Sequence[Path]) -> str:
    if not paths:
        raise EtfMinsBootstrapError("etf_mins_bootstrap_parquet_paths_empty.")
    return (
        f"read_parquet({_duckdb_path_list(paths)}, hive_partitioning=false, "
        "union_by_name=true, filename=true)"
    )


def _duckdb_path_list(paths: Sequence[Path]) -> str:
    return "[" + ", ".join(duckdb_string(path) for path in paths) + "]"


def _target_expected_values(
    paths: Sequence[Path],
    expected_by_path: Mapping[str, tuple[str, str]],
) -> str:
    return ", ".join(
        "("
        + ", ".join(
            (
                duckdb_string(path),
                duckdb_string(expected_by_path[str(path)][0]),
                duckdb_string(expected_by_path[str(path)][1]),
            )
        )
        + ")"
        for path in paths
    )


def _load_duckdb_postgres_extension(connection: Any) -> None:
    try:
        connection.execute("LOAD postgres")
        return
    except Exception:  # noqa: BLE001 - local DuckDB may need one install.
        try:
            connection.execute("INSTALL postgres")
            connection.execute("LOAD postgres")
        except Exception as error:
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_postgres_extension_unavailable."
            ) from error


def _attach_prod_etf_mins_readonly(
    connection: Any,
    *,
    postgres_connection_string: str,
) -> None:
    try:
        connection.execute(
            build_prod_etf_mins_duckdb_attach_sql(conninfo=postgres_connection_string)
        )
    except Exception:  # noqa: BLE001 - never expose Prod connection details.
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_prod_attach_failed: connection details are omitted."
        ) from None


def _assert_roots_available(*, lake_root: Path, staging_root: Path) -> None:
    for name, root in (("lake_root", lake_root), ("staging_root", staging_root)):
        if not root.is_dir() or not os.access(root, os.R_OK | os.W_OK):
            raise EtfMinsBootstrapError(
                f"etf_mins_bootstrap_{name}_unavailable: {root}."
            )
    if os.stat(lake_root).st_dev != os.stat(staging_root).st_dev:
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_cross_filesystem_forbidden: staging and formal "
            "Lake must share one filesystem."
        )


def _write_immutable_json(path: Path, payload: Mapping[str, object]) -> None:
    if path.exists():
        existing = _load_json(path, label="immutable JSON")
        if existing != dict(payload):
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_immutable_report_conflict: existing content "
                "will not be overwritten."
            )
        return
    _atomic_write_json(path, payload)


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    candidate = path.with_name(f".{path.name}.candidate-{uuid.uuid4().hex}")
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )
    try:
        candidate.write_text(serialized + "\n", encoding="utf-8")
        os.replace(candidate, path)
    finally:
        if candidate.exists():
            candidate.unlink()


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise EtfMinsBootstrapError(f"{label} does not exist: {path}.") from error
    except json.JSONDecodeError as error:
        raise EtfMinsBootstrapError(f"{label} is not valid JSON: {path}.") from error
    if not isinstance(payload, dict):
        raise EtfMinsBootstrapError(f"{label} must contain one JSON object.")
    return payload


def _normalize_operation_id(value: object) -> str:
    normalized = str(value or "").strip()
    if (
        not normalized
        or normalized in {".", ".."}
        or "/" in normalized
        or "\\" in normalized
    ):
        raise EtfMinsBootstrapError("etf_mins_bootstrap_operation_id_invalid.")
    return normalized


def _normalize_created_at(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise EtfMinsBootstrapError("etf_mins_bootstrap_created_at_timezone_required.")
    return value.astimezone(ZoneInfo("Asia/Shanghai")).isoformat()


def _normalize_trade_dates(values: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(normalize_etf_mins_trade_date(value) for value in values)
    if len(normalized) != len(set(normalized)) or normalized != tuple(
        sorted(normalized)
    ):
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_trade_dates_invalid: dates must be unique and sorted."
        )
    return normalized


def _string_sequence(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise EtfMinsBootstrapError(
            f"etf_mins_bootstrap_plan_field_invalid: {field_name}."
        )
    return tuple(str(item) for item in value)


def _int_mapping(value: object, field_name: str) -> Mapping[str, int]:
    if not isinstance(value, Mapping):
        raise EtfMinsBootstrapError(
            f"etf_mins_bootstrap_plan_field_invalid: {field_name}."
        )
    return {str(key): int(item) for key, item in value.items()}


def _chunks(values: Sequence[str], size: int) -> Iterable[tuple[str, ...]]:
    for offset in range(0, len(values), size):
        yield tuple(values[offset : offset + size])


def _batch_key(source_freq: str, trade_dates: Sequence[str]) -> str:
    return f"{source_freq}|{trade_dates[0]}|{trade_dates[-1]}"


def _target_key(source_freq: str, trade_date: str) -> str:
    return f"{source_freq}|{trade_date}"


def _datetime_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return str(value)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def plan_etf_mins_bootstrap_partitions(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path,
    staging_root: Path,
    duckdb: DuckDBResource,
    final_report_path: Path,
) -> EtfMinsBootstrapPartitionReport:
    """Dry-run the exact dynamic-partition delta for one closed operation."""

    evidence = _load_etf_mins_bootstrap_physical_evidence(
        lake_root=lake_root,
        staging_root=staging_root,
        duckdb=duckdb,
        final_report_path=final_report_path,
    )
    planned = evidence.raw_evidence.plan.expected_trade_dates
    registered = {
        normalize_etf_mins_trade_date(value)
        for value in instance.get_dynamic_partitions(_ETF_MINS_PARTITION_SET_NAME)
    }
    missing = tuple(value for value in planned if value not in registered)
    return _partition_report(
        mode="dry-run",
        evidence=evidence,
        planned=planned,
        missing=missing,
        added_count=0,
    )


def register_etf_mins_bootstrap_partitions(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path,
    staging_root: Path,
    duckdb: DuckDBResource,
    final_report_path: Path,
    confirm_partition_write: bool,
) -> EtfMinsBootstrapPartitionReport:
    """Add only the frozen operation's missing ETF-minute partition keys."""

    if not confirm_partition_write:
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_partition_confirmation_required."
        )
    evidence = _load_etf_mins_bootstrap_physical_evidence(
        lake_root=lake_root,
        staging_root=staging_root,
        duckdb=duckdb,
        final_report_path=final_report_path,
    )
    planned = evidence.raw_evidence.plan.expected_trade_dates
    registered_before = {
        normalize_etf_mins_trade_date(value)
        for value in instance.get_dynamic_partitions(_ETF_MINS_PARTITION_SET_NAME)
    }
    missing = tuple(value for value in planned if value not in registered_before)
    if missing:
        instance.add_dynamic_partitions(_ETF_MINS_PARTITION_SET_NAME, list(missing))
    registered_after = {
        normalize_etf_mins_trade_date(value)
        for value in instance.get_dynamic_partitions(_ETF_MINS_PARTITION_SET_NAME)
    }
    still_missing = tuple(value for value in planned if value not in registered_after)
    if still_missing:
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_partition_registration_incomplete."
        )
    return _partition_report(
        mode="apply",
        evidence=evidence,
        planned=planned,
        missing=(),
        added_count=len(missing),
    )


def plan_etf_mins_bootstrap_events(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path,
    staging_root: Path,
    duckdb: DuckDBResource,
    final_report_path: Path,
) -> EtfMinsBootstrapEventReport:
    """Build a bounded, read-only materialization/check event delta."""

    context = _build_etf_mins_bootstrap_event_context(
        instance=instance,
        lake_root=lake_root,
        staging_root=staging_root,
        duckdb=duckdb,
        final_report_path=final_report_path,
    )
    return _event_report(
        mode="dry-run",
        context=context,
        reported_materializations=0,
        reported_checks=0,
    )


def apply_etf_mins_bootstrap_events(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path,
    staging_root: Path,
    duckdb: DuckDBResource,
    final_report_path: Path,
    confirm_event_write: bool,
) -> EtfMinsBootstrapEventReport:
    """Append only missing equivalent runless facts; never replace event facts."""

    if not confirm_event_write:
        raise EtfMinsBootstrapError("etf_mins_bootstrap_event_confirmation_required.")
    context = _build_etf_mins_bootstrap_event_context(
        instance=instance,
        lake_root=lake_root,
        staging_root=staging_root,
        duckdb=duckdb,
        final_report_path=final_report_path,
    )
    for spec in context.pending_materialization_specs:
        instance.report_runless_asset_event(
            dg.AssetMaterialization(
                asset_key=spec.asset_key,
                partition=spec.partition_key,
                metadata=spec.metadata,
            )
        )
    materializations, _ = _load_latest_etf_mins_materializations(
        instance=instance,
        specs=context.materialization_specs,
    )
    for spec in context.materialization_specs:
        record = materializations.get(_materialization_spec_key(spec))
        if record is None or not _materialization_record_matches(record, spec):
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_materialization_post_write_mismatch."
            )

    reported_checks = 0
    for spec in context.pending_check_specs:
        materialization = materializations[_check_materialization_key(spec)]
        target = AssetCheckEvaluationTargetMaterializationData(
            storage_id=int(materialization.storage_id),
            run_id=materialization.run_id,
            timestamp=materialization.timestamp,
        )
        instance.report_runless_asset_event(
            dg.AssetCheckEvaluation(
                asset_key=spec.asset_key,
                check_name=spec.check_name,
                passed=spec.passed,
                blocking=True,
                partition=spec.partition_key,
                target_materialization_data=target,
                metadata=spec.metadata,
            )
        )
        reported_checks += 1
    return _event_report(
        mode="apply",
        context=context,
        reported_materializations=len(context.pending_materialization_specs),
        reported_checks=reported_checks,
    )


def audit_etf_mins_bootstrap_events(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path,
    staging_root: Path,
    duckdb: DuckDBResource,
    final_report_path: Path,
) -> EtfMinsBootstrapEventReport:
    """Post-audit aggregate event closure plus three bounded recent samples."""

    context = _build_etf_mins_bootstrap_event_context(
        instance=instance,
        lake_root=lake_root,
        staging_root=staging_root,
        duckdb=duckdb,
        final_report_path=final_report_path,
    )
    if context.pending_materialization_specs or context.pending_check_specs:
        raise EtfMinsBootstrapError("etf_mins_bootstrap_event_post_audit_incomplete.")
    recent = _recent_etf_mins_check_trade_dates(context.planned_trade_dates)
    sample_dates = _sample_etf_mins_trade_dates(recent)
    return _event_report(
        mode="post-audit",
        context=context,
        reported_materializations=0,
        reported_checks=0,
        sample_dates=sample_dates,
    )


def _partition_report(
    *,
    mode: str,
    evidence: _EtfMinsBootstrapPhysicalEvidence,
    planned: tuple[str, ...],
    missing: tuple[str, ...],
    added_count: int,
) -> EtfMinsBootstrapPartitionReport:
    return EtfMinsBootstrapPartitionReport(
        mode=mode,
        operation_id=evidence.report.operation_id,
        plan_fingerprint=evidence.report.plan_fingerprint,
        physical_final_report_hash=evidence.report.report_hash,
        partition_set_name=_ETF_MINS_PARTITION_SET_NAME,
        planned_partition_count=len(planned),
        existing_planned_partition_count=len(planned) - len(missing),
        missing_partition_count=len(missing),
        added_partition_count=added_count,
        planned_trade_dates=planned,
        missing_trade_dates=missing,
    )


def _event_report(
    *,
    mode: str,
    context: _EtfMinsBootstrapEventContext,
    reported_materializations: int,
    reported_checks: int,
    sample_dates: tuple[str, ...] = (),
) -> EtfMinsBootstrapEventReport:
    raw_count = sum(spec.layer == "raw" for spec in context.materialization_specs)
    silver_count = sum(spec.layer == "silver" for spec in context.materialization_specs)
    remaining_materializations = (
        len(context.pending_materialization_specs) - reported_materializations
    )
    remaining_checks = len(context.pending_check_specs) - reported_checks
    return EtfMinsBootstrapEventReport(
        mode=mode,
        operation_id=context.evidence.report.operation_id,
        plan_fingerprint=context.evidence.report.plan_fingerprint,
        physical_final_report_hash=context.evidence.report.report_hash,
        partition_set_name=_ETF_MINS_PARTITION_SET_NAME,
        registered_partition_count=len(context.registered_trade_dates),
        raw_materialization_count=raw_count,
        silver_materialization_count=silver_count,
        existing_equivalent_materialization_count=(
            len(context.materialization_specs) - remaining_materializations
        ),
        pending_materialization_count=remaining_materializations,
        reported_materialization_count=reported_materializations,
        recent_check_trade_dates=_recent_etf_mins_check_trade_dates(
            context.planned_trade_dates
        ),
        planned_check_event_count=len(context.check_specs),
        existing_equivalent_check_event_count=(
            len(context.check_specs) - remaining_checks
        ),
        pending_check_event_count=remaining_checks,
        reported_check_event_count=reported_checks,
        materialization_query_count=context.materialization_query_count,
        check_history_query_count=context.check_history_query_count,
        verified_file_count=context.evidence.verified_file_count,
        verified_file_bytes=context.evidence.verified_file_bytes,
        sample_trade_dates=sample_dates,
    )


def _load_etf_mins_bootstrap_physical_evidence(
    *,
    lake_root: Path,
    staging_root: Path,
    duckdb: DuckDBResource,
    final_report_path: Path,
) -> _EtfMinsBootstrapPhysicalEvidence:
    operation_root, operation_id = validate_etf_mins_bootstrap_operation_path(
        final_report_path,
        staging_root=staging_root,
    )
    if (
        final_report_path.parent.resolve(strict=False) != operation_root
        or final_report_path.name != _PHYSICAL_FINAL_REPORT_FILENAME
    ):
        raise EtfMinsBootstrapError("etf_mins_bootstrap_physical_report_path_invalid.")
    report_payload = _load_json(
        final_report_path,
        label="ETF minute physical final report",
    )
    if (
        report_payload.get("bootstrap_kind") != ETF_MINS_BOOTSTRAP_KIND
        or int(report_payload.get("schema_version", 0))
        != ETF_MINS_BOOTSTRAP_SCHEMA_VERSION
        or report_payload.get("operation_id") != operation_id
    ):
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_physical_report_identity_invalid."
        )
    report = _silver_apply_report_from_payload(report_payload, final_report_path)
    raw_evidence = load_etf_mins_bootstrap_raw_evidence(
        lake_root=lake_root,
        duckdb=duckdb,
        raw_final_report_path=operation_root / "raw_final_report.json",
    )
    decision_summary_path = operation_root / "raw_decision_summary.json"
    decision_manifest_path = operation_root / "raw_partition_decision_manifest.parquet"
    decision_summary, selected_decision_rows, observation_hash = (
        _load_etf_mins_silver_decision_evidence(
            operation_root=operation_root,
            operation_id=operation_id,
            raw_evidence=raw_evidence,
            decision_summary_path=decision_summary_path,
            decision_manifest_path=decision_manifest_path,
            duckdb=duckdb,
        )
    )
    policy = get_etf_mins_raw_decision_policy(
        str(decision_summary["approved_policy_version"])
    )
    raw_rows_by_key = {
        _target_key(str(row["source_freq"]), str(row["trade_date"])): row
        for row in raw_evidence.finalized_raw_manifest
    }
    selected_decision_by_key = {
        _target_key(str(row["source_freq"]), str(row["trade_date"])): row
        for row in selected_decision_rows
    }
    _assert_etf_mins_silver_decision_scope(
        raw_rows_by_key=raw_rows_by_key,
        decision_rows_by_key=selected_decision_by_key,
        raw_evidence=raw_evidence,
        policy=policy,
    )
    decision_rows = _load_etf_mins_full_decision_rows(
        duckdb=duckdb,
        path=decision_manifest_path,
    )
    if {
        _target_key(str(row["source_freq"]), str(row["trade_date"]))
        for row in decision_rows
    } != set(selected_decision_by_key):
        raise EtfMinsBootstrapError("etf_mins_bootstrap_event_decision_scope_invalid.")

    work_manifest_path = operation_root / _SILVER_WORK_MANIFEST_FILENAME
    finalized_silver_path = operation_root / _FINALIZED_SILVER_MANIFEST_FILENAME
    checkpoint_path = operation_root / _SILVER_CHECKPOINT_FILENAME
    if (
        report.silver_work_manifest_path != work_manifest_path
        or report.finalized_silver_manifest_path != finalized_silver_path
        or report.checkpoint_path != checkpoint_path
        or report.final_report_path != final_report_path
    ):
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_physical_report_artifact_path_invalid."
        )
    work_rows = _load_etf_mins_typed_manifest(
        path=work_manifest_path,
        columns=_SILVER_WORK_MANIFEST_COLUMNS,
        duckdb=duckdb,
    )
    finalized_silver_rows = _load_etf_mins_typed_manifest(
        path=finalized_silver_path,
        columns=_FINALIZED_SILVER_MANIFEST_COLUMNS,
        duckdb=duckdb,
    )
    work_hash = compute_etf_mins_bootstrap_manifest_hash(
        work_rows,
        key_fields=("source_freq", "trade_date"),
    )
    finalized_silver_hash = compute_etf_mins_bootstrap_manifest_hash(
        finalized_silver_rows,
        key_fields=("source_freq", "trade_date"),
    )
    checkpoint = _load_json(checkpoint_path, label="ETF minute Silver checkpoint")
    checkpoint_hash = _validate_etf_mins_silver_checkpoint(
        checkpoint,
        raw_evidence=raw_evidence,
        decision_summary=decision_summary,
        work_manifest_hash=work_hash,
    )
    required_report_values = {
        "plan_fingerprint": raw_evidence.plan.plan_fingerprint,
        "raw_final_report_hash": raw_evidence.raw_apply_report.report_hash,
        "raw_observation_summary_hash": observation_hash,
        "raw_decision_summary_hash": decision_summary["raw_decision_summary_hash"],
        "raw_partition_decision_manifest_hash": decision_summary[
            "raw_partition_decision_manifest"
        ]["sha256"],
        "finalized_raw_manifest_hash": (
            raw_evidence.raw_apply_report.finalized_raw_manifest_hash
        ),
        "silver_work_manifest_hash": work_hash,
        "finalized_silver_manifest_hash": finalized_silver_hash,
        "checkpoint_hash": checkpoint_hash,
        "basic_raw_snapshot_hash": raw_evidence.plan.basic_raw_snapshot_hash,
        "basic_silver_content_hash": raw_evidence.plan.basic_silver_content_hash,
        "gap_policy_version": policy.version,
        "gap_policy_hash": policy.policy_hash,
    }
    if any(
        report_payload.get(field) != expected
        for field, expected in required_report_values.items()
    ):
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_physical_report_evidence_drift."
        )
    _assert_protected_manifest_unchanged(
        plan=raw_evidence.plan,
        lake_root=lake_root,
    )

    eligible_keys = {
        _target_key(str(row["source_freq"]), str(row["trade_date"]))
        for row in selected_decision_rows
        if bool(row["silver_eligible"])
    }
    finalized_silver_by_key = {
        _target_key(str(row["source_freq"]), str(row["trade_date"])): row
        for row in finalized_silver_rows
    }
    if set(finalized_silver_by_key) != eligible_keys:
        raise EtfMinsBootstrapError("etf_mins_bootstrap_event_silver_scope_invalid.")
    silver_bytes = 0
    for key, row in finalized_silver_by_key.items():
        raw_row = raw_rows_by_key[key]
        source_freq = str(row["source_freq"])
        trade_date = str(row["trade_date"])
        silver_path = silver_etf_mins_path(lake_root, source_freq, trade_date)
        if (
            row.get("operation_id") != operation_id
            or row.get("plan_fingerprint") != raw_evidence.plan.plan_fingerprint
            or row.get("formal_raw_sha256") != raw_row["formal_raw_sha256"]
            or int(row["formal_raw_row_count"]) != int(raw_row["formal_raw_row_count"])
            or row.get("formal_silver_relative_path")
            != silver_path.relative_to(lake_root).as_posix()
            or row.get("disposition") not in {"added", "reused"}
            or not silver_path.is_file()
            or int(row["formal_silver_size_bytes"]) != silver_path.stat().st_size
            or row.get("formal_silver_sha256") != _sha256_file(silver_path)
        ):
            raise EtfMinsBootstrapError("etf_mins_bootstrap_event_silver_file_changed.")
        silver_bytes += int(row["formal_silver_size_bytes"])
    raw_bytes = sum(
        int(row["formal_raw_size_bytes"]) for row in raw_evidence.finalized_raw_manifest
    )
    if (
        report.raw_file_count != len(raw_evidence.finalized_raw_manifest)
        or report.silver_file_count != len(finalized_silver_rows)
        or report.raw_row_count
        != sum(
            int(row["formal_raw_row_count"])
            for row in raw_evidence.finalized_raw_manifest
        )
        or report.silver_row_count
        != sum(int(row["formal_silver_row_count"]) for row in finalized_silver_rows)
    ):
        raise EtfMinsBootstrapError("etf_mins_bootstrap_physical_report_count_drift.")
    return _EtfMinsBootstrapPhysicalEvidence(
        report=report,
        report_payload=report_payload,
        raw_evidence=raw_evidence,
        decision_rows=decision_rows,
        finalized_silver_rows=finalized_silver_rows,
        verified_file_count=(
            len(raw_evidence.finalized_raw_manifest) + len(finalized_silver_rows)
        ),
        verified_file_bytes=raw_bytes + silver_bytes,
    )


def _load_etf_mins_full_decision_rows(
    *,
    duckdb: DuckDBResource,
    path: Path,
) -> tuple[Mapping[str, object], ...]:
    try:
        with duckdb.connect() as connection:
            cursor = connection.execute(
                f"SELECT * FROM {read_parquet(path, hive_partitioning=False)} "
                "ORDER BY source_freq, trade_date"
            )
            columns = tuple(str(item[0]) for item in cursor.description)
            return tuple(
                dict(zip(columns, row, strict=True)) for row in cursor.fetchall()
            )
    except Exception:  # noqa: BLE001 - normalize immutable evidence failures.
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_event_decision_manifest_unreadable."
        ) from None


def _build_etf_mins_bootstrap_event_context(
    *,
    instance: dg.DagsterInstance,
    lake_root: Path,
    staging_root: Path,
    duckdb: DuckDBResource,
    final_report_path: Path,
) -> _EtfMinsBootstrapEventContext:
    evidence = _load_etf_mins_bootstrap_physical_evidence(
        lake_root=lake_root,
        staging_root=staging_root,
        duckdb=duckdb,
        final_report_path=final_report_path,
    )
    planned = evidence.raw_evidence.plan.expected_trade_dates
    registered = tuple(
        sorted(
            {
                normalize_etf_mins_trade_date(value)
                for value in instance.get_dynamic_partitions(
                    _ETF_MINS_PARTITION_SET_NAME
                )
            }
        )
    )
    missing_registered = tuple(value for value in planned if value not in registered)
    if missing_registered:
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_event_partitions_not_registered."
        )
    materialization_specs, check_specs = _build_etf_mins_event_specs(
        evidence=evidence,
        lake_root=lake_root,
    )
    if len(materialization_specs) > 2 * evidence.report.raw_file_count:
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_materialization_event_budget_exceeded."
        )
    if len(check_specs) > _ETF_MINS_MAX_CHECK_EVENT_COUNT:
        raise EtfMinsBootstrapError("etf_mins_bootstrap_check_event_budget_exceeded.")
    materializations, materialization_query_count = (
        _load_latest_etf_mins_materializations(
            instance=instance,
            specs=materialization_specs,
        )
    )
    pending_materializations: list[_EtfMinsMaterializationEventSpec] = []
    for spec in materialization_specs:
        record = materializations.get(_materialization_spec_key(spec))
        if record is None:
            pending_materializations.append(spec)
        elif not _materialization_record_matches(record, spec):
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_materialization_event_conflict."
            )
    checks, check_history_query_count = _load_latest_etf_mins_checks(
        instance=instance,
        specs=check_specs,
    )
    pending_checks: list[_EtfMinsCheckEventSpec] = []
    for spec in check_specs:
        check_key = _check_spec_key(spec)
        record = checks.get(check_key)
        materialization = materializations.get(_check_materialization_key(spec))
        if record is None:
            pending_checks.append(spec)
            continue
        if materialization is None or not _check_record_matches(
            record,
            spec,
            target_storage_id=int(materialization.storage_id),
        ):
            raise EtfMinsBootstrapError("etf_mins_bootstrap_check_event_conflict.")
    return _EtfMinsBootstrapEventContext(
        evidence=evidence,
        planned_trade_dates=planned,
        registered_trade_dates=registered,
        materialization_specs=materialization_specs,
        check_specs=check_specs,
        materializations_by_key=materializations,
        checks_by_key=checks,
        pending_materialization_specs=tuple(pending_materializations),
        pending_check_specs=tuple(pending_checks),
        materialization_query_count=materialization_query_count,
        check_history_query_count=check_history_query_count,
    )


def _build_etf_mins_event_specs(
    *,
    evidence: _EtfMinsBootstrapPhysicalEvidence,
    lake_root: Path,
) -> tuple[
    tuple[_EtfMinsMaterializationEventSpec, ...],
    tuple[_EtfMinsCheckEventSpec, ...],
]:
    raw_rows = evidence.raw_evidence.finalized_raw_manifest
    decision_by_key = {
        _target_key(str(row["source_freq"]), str(row["trade_date"])): row
        for row in evidence.decision_rows
    }
    silver_by_key = {
        _target_key(str(row["source_freq"]), str(row["trade_date"])): row
        for row in evidence.finalized_silver_rows
    }
    raw_asset_by_freq = {
        source_freq: asset
        for source_freq, asset in zip(
            ETF_MINS_SOURCE_FREQS,
            RAW_ETF_MINS_ASSETS,
            strict=True,
        )
    }
    silver_asset_by_freq = {
        source_freq: asset
        for source_freq, asset in zip(
            ETF_MINS_SOURCE_FREQS,
            SILVER_ETF_MINS_ASSETS,
            strict=True,
        )
    }
    recent_dates = set(
        _recent_etf_mins_check_trade_dates(
            evidence.raw_evidence.plan.expected_trade_dates
        )
    )
    materializations: list[_EtfMinsMaterializationEventSpec] = []
    checks: list[_EtfMinsCheckEventSpec] = []
    for raw_row in raw_rows:
        source_freq = str(raw_row["source_freq"])
        trade_date = str(raw_row["trade_date"])
        key = _target_key(source_freq, trade_date)
        decision_row = decision_by_key[key]
        raw_spec = _raw_etf_mins_materialization_spec(
            evidence=evidence,
            lake_root=lake_root,
            asset_key=raw_asset_by_freq[source_freq].key,
            raw_row=raw_row,
        )
        materializations.append(raw_spec)
        silver_row = silver_by_key.get(key)
        if silver_row is not None:
            materializations.append(
                _silver_etf_mins_materialization_spec(
                    evidence=evidence,
                    lake_root=lake_root,
                    asset_key=silver_asset_by_freq[source_freq].key,
                    raw_row=raw_row,
                    decision_row=decision_row,
                    silver_row=silver_row,
                )
            )
        if trade_date not in recent_dates:
            continue
        checks.extend(
            _raw_etf_mins_check_specs(
                evidence=evidence,
                lake_root=lake_root,
                asset_key=raw_asset_by_freq[source_freq].key,
                raw_row=raw_row,
                decision_row=decision_row,
            )
        )
        if silver_row is not None:
            checks.extend(
                _silver_etf_mins_check_specs(
                    evidence=evidence,
                    lake_root=lake_root,
                    asset_key=silver_asset_by_freq[source_freq].key,
                    raw_row=raw_row,
                    silver_row=silver_row,
                )
            )
    return tuple(materializations), tuple(checks)


def _raw_etf_mins_materialization_spec(
    *,
    evidence: _EtfMinsBootstrapPhysicalEvidence,
    lake_root: Path,
    asset_key: dg.AssetKey,
    raw_row: Mapping[str, object],
) -> _EtfMinsMaterializationEventSpec:
    plan = evidence.raw_evidence.plan
    reference = evidence.raw_evidence.basic_reference
    source_freq = str(raw_row["source_freq"])
    trade_date = str(raw_row["trade_date"])
    path = raw_etf_mins_path(lake_root, source_freq, trade_date)
    identity = {
        "event_kind": "etf_mins_bootstrap_materialization",
        "operation_id": plan.operation_id,
        "plan_fingerprint": plan.plan_fingerprint,
        "physical_final_report_hash": evidence.report.report_hash,
        "asset_key": asset_key.to_user_string(),
        "partition_key": trade_date,
        "source_freq": source_freq,
        "layer": "raw",
        "file_sha256": raw_row["formal_raw_sha256"],
        "row_count": int(raw_row["formal_raw_row_count"]),
        "basic_raw_snapshot_hash": plan.basic_raw_snapshot_hash,
        "basic_silver_content_hash": plan.basic_silver_content_hash,
    }
    metadata = build_materialization_metadata(
        uri=path,
        row_count=int(raw_row["formal_raw_row_count"]),
        observed_columns=ETF_MINS_SOURCE_COLUMNS,
        extra_metadata={
            "partition_key": trade_date,
            "source_freq": source_freq,
            "source_method": "prod_db_readonly",
            "source_row_count": int(raw_row["source_row_count"]),
            "code_count": int(raw_row["source_code_count"]),
            "query_count": 1,
            "elapsed_ms": 0,
            "basic_raw_snapshot_hash": plan.basic_raw_snapshot_hash,
            "basic_silver_content_hash": plan.basic_silver_content_hash,
            "basic_raw_observed_at": plan.basic_raw_observed_at,
            "basic_silver_observed_at": plan.basic_silver_observed_at,
            "basic_reference_fingerprint": reference.reference_fingerprint,
            "eligibility_as_of": plan.eligibility_as_of,
            "requestable_code_count": plan.requestable_code_count,
            "requestable_code_hash": plan.requestable_code_hash,
            "expected_count": int(raw_row["expected_count"]),
            "present_count": int(raw_row["present_count"]),
            "missing_count": int(raw_row["missing_count"]),
            "known_non_required_present_count": int(
                raw_row["known_non_required_present_count"]
            ),
            "retained_legacy_count": int(raw_row["retained_legacy_count"]),
            "unexplained_new_count": int(raw_row["unexplained_new_count"]),
            "file_sha256": raw_row["formal_raw_sha256"],
            "write_disposition": raw_row["disposition"],
            "policy_state": "unclassified",
            "silver_eligible": False,
            "bootstrap_event_backfill": True,
            "bootstrap_operation_id": plan.operation_id,
            "plan_fingerprint": plan.plan_fingerprint,
            "physical_final_report_hash": evidence.report.report_hash,
            "event_identity_hash": compute_etf_mins_bootstrap_payload_hash(identity),
        },
    )
    return _EtfMinsMaterializationEventSpec(
        asset_key=asset_key,
        partition_key=trade_date,
        source_freq=source_freq,
        layer="raw",
        metadata=metadata,
    )


def _silver_etf_mins_materialization_spec(
    *,
    evidence: _EtfMinsBootstrapPhysicalEvidence,
    lake_root: Path,
    asset_key: dg.AssetKey,
    raw_row: Mapping[str, object],
    decision_row: Mapping[str, object],
    silver_row: Mapping[str, object],
) -> _EtfMinsMaterializationEventSpec:
    plan = evidence.raw_evidence.plan
    reference = evidence.raw_evidence.basic_reference
    source_freq = str(raw_row["source_freq"])
    trade_date = str(raw_row["trade_date"])
    raw_path = raw_etf_mins_path(lake_root, source_freq, trade_date)
    silver_path = silver_etf_mins_path(lake_root, source_freq, trade_date)
    reason_codes = _decision_reason_codes(decision_row)
    identity = {
        "event_kind": "etf_mins_bootstrap_materialization",
        "operation_id": plan.operation_id,
        "plan_fingerprint": plan.plan_fingerprint,
        "physical_final_report_hash": evidence.report.report_hash,
        "asset_key": asset_key.to_user_string(),
        "partition_key": trade_date,
        "source_freq": source_freq,
        "layer": "silver",
        "raw_sha256": raw_row["formal_raw_sha256"],
        "silver_sha256": silver_row["formal_silver_sha256"],
        "row_count": int(silver_row["formal_silver_row_count"]),
        "decision": decision_row["decision"],
        "decision_reason_codes": reason_codes,
    }
    metadata = build_materialization_metadata(
        uri=silver_path,
        row_count=int(silver_row["formal_silver_row_count"]),
        observed_columns=ETF_MINS_SOURCE_COLUMNS,
        extra_metadata={
            "partition_key": trade_date,
            "source_freq": source_freq,
            "source_method": "direct_lake_bootstrap_exact_copy",
            "code_count": int(raw_row["source_code_count"]),
            "raw_uri": str(raw_path),
            "raw_sha256": raw_row["formal_raw_sha256"],
            "silver_sha256": silver_row["formal_silver_sha256"],
            "write_disposition": silver_row["disposition"],
            "basic_raw_snapshot_hash": plan.basic_raw_snapshot_hash,
            "basic_silver_content_hash": plan.basic_silver_content_hash,
            "basic_raw_observed_at": plan.basic_raw_observed_at,
            "basic_silver_observed_at": plan.basic_silver_observed_at,
            "basic_reference_fingerprint": reference.reference_fingerprint,
            "eligibility_as_of": plan.eligibility_as_of,
            "requestable_code_hash": plan.requestable_code_hash,
            "gap_policy_version": evidence.report_payload["gap_policy_version"],
            "bar_domain_decision": decision_row["decision"],
            "bar_domain_reason_codes": list(reason_codes),
            "bootstrap_event_backfill": True,
            "bootstrap_operation_id": plan.operation_id,
            "plan_fingerprint": plan.plan_fingerprint,
            "physical_final_report_hash": evidence.report.report_hash,
            "event_identity_hash": compute_etf_mins_bootstrap_payload_hash(identity),
        },
    )
    return _EtfMinsMaterializationEventSpec(
        asset_key=asset_key,
        partition_key=trade_date,
        source_freq=source_freq,
        layer="silver",
        metadata=metadata,
    )


def _raw_etf_mins_check_specs(
    *,
    evidence: _EtfMinsBootstrapPhysicalEvidence,
    lake_root: Path,
    asset_key: dg.AssetKey,
    raw_row: Mapping[str, object],
    decision_row: Mapping[str, object],
) -> tuple[_EtfMinsCheckEventSpec, ...]:
    source_freq = str(raw_row["source_freq"])
    trade_date = str(raw_row["trade_date"])
    minutes = int(source_freq.removesuffix("min"))
    path = raw_etf_mins_path(lake_root, source_freq, trade_date)
    common = {
        "source_method": "direct_lake_bootstrap",
        "bootstrap_event_backfill": True,
        "bootstrap_operation_id": evidence.report.operation_id,
        "plan_fingerprint": evidence.report.plan_fingerprint,
        "physical_final_report_hash": evidence.report.report_hash,
        "partition_key": trade_date,
        "source_freq": source_freq,
    }
    file_evidence = {
        "raw_sha256": raw_row["formal_raw_sha256"],
        "reason_code": "ok",
        "reason_codes": [],
        "summary": "ETF 分钟 Raw 文件合同已由 Bootstrap 稳定校验验收。",
        "next_action": "无需处理。",
    }
    scope_evidence = {
        "raw_sha256": raw_row["formal_raw_sha256"],
        "basic_reference_fingerprint": (
            evidence.raw_evidence.basic_reference.reference_fingerprint
        ),
        "expected_count": int(raw_row["expected_count"]),
        "present_count": int(raw_row["present_count"]),
        "missing_count": int(raw_row["missing_count"]),
        "known_non_required_present_count": int(
            raw_row["known_non_required_present_count"]
        ),
        "retained_legacy_count": int(raw_row["retained_legacy_count"]),
        "unexplained_new_count": int(raw_row["unexplained_new_count"]),
        "reason_code": "ok",
        "reason_codes": [],
        "summary": "ETF 分钟 Raw 冻结 Basic 请求范围已由 Bootstrap 验收。",
        "next_action": "无需处理。",
    }
    reasons = _decision_reason_codes(decision_row)
    issue_counts = _decision_issue_counts(decision_row)
    blocking_failure_count = sum(
        issue_counts.get(reason, 0)
        for reason in get_etf_mins_raw_decision_policy(
            str(decision_row["approved_policy_version"])
        ).blocking_reason_codes
    )
    bar_evidence = {
        "raw_sha256": raw_row["formal_raw_sha256"],
        "gap_policy_version": decision_row["approved_policy_version"],
        "gap_policy_hash": decision_row["approved_policy_hash"],
        "bar_domain_decision": decision_row["decision"],
        "bar_domain_reason_codes": list(reasons),
        "issue_counts": issue_counts,
        "reason_code": "ok" if not reasons else ",".join(reasons),
        "reason_codes": list(reasons),
        "summary": (
            "ETF 分钟 N3 已按批准 policy 准入。"
            if bool(decision_row["silver_eligible"])
            else "ETF 分钟 N3 判定 blocked，禁止进入 Silver。"
        ),
        "next_action": (
            "无需处理；WARN 原因已记录。"
            if bool(decision_row["silver_eligible"])
            else "查看 decision manifest 后处理数据事实。"
        ),
    }
    check_names = raw_etf_mins_check_names(minutes)
    return (
        _make_etf_mins_check_spec(
            evidence=evidence,
            asset_key=asset_key,
            partition_key=trade_date,
            check_name=check_names[0],
            passed=True,
            scope=CheckScope.SCHEMA,
            checked_row_count=int(raw_row["formal_raw_row_count"]),
            failed_row_count=0,
            file_path=path,
            extra_metadata={**common, **file_evidence},
        ),
        _make_etf_mins_check_spec(
            evidence=evidence,
            asset_key=asset_key,
            partition_key=trade_date,
            check_name=check_names[1],
            passed=True,
            scope=CheckScope.REFERENTIAL_INTEGRITY,
            checked_row_count=int(raw_row["formal_raw_row_count"]),
            failed_row_count=0,
            file_path=path,
            extra_metadata={**common, **scope_evidence},
        ),
        _make_etf_mins_check_spec(
            evidence=evidence,
            asset_key=asset_key,
            partition_key=trade_date,
            check_name=check_names[2],
            passed=bool(decision_row["silver_eligible"]),
            scope=CheckScope.VALUE_SANITY,
            checked_row_count=int(raw_row["formal_raw_row_count"]),
            failed_row_count=blocking_failure_count,
            file_path=path,
            extra_metadata={**common, **bar_evidence},
        ),
    )


def _silver_etf_mins_check_specs(
    *,
    evidence: _EtfMinsBootstrapPhysicalEvidence,
    lake_root: Path,
    asset_key: dg.AssetKey,
    raw_row: Mapping[str, object],
    silver_row: Mapping[str, object],
) -> tuple[_EtfMinsCheckEventSpec, ...]:
    source_freq = str(raw_row["source_freq"])
    trade_date = str(raw_row["trade_date"])
    minutes = int(source_freq.removesuffix("min"))
    raw_path = raw_etf_mins_path(lake_root, source_freq, trade_date)
    silver_path = silver_etf_mins_path(lake_root, source_freq, trade_date)
    common = {
        "source_method": "direct_lake_bootstrap",
        "bootstrap_event_backfill": True,
        "bootstrap_operation_id": evidence.report.operation_id,
        "plan_fingerprint": evidence.report.plan_fingerprint,
        "physical_final_report_hash": evidence.report.report_hash,
        "partition_key": trade_date,
        "source_freq": source_freq,
        "reason_code": "ok",
        "reason_codes": [],
        "next_action": "无需处理。",
    }
    check_names = silver_etf_mins_check_names(minutes)
    return (
        _make_etf_mins_check_spec(
            evidence=evidence,
            asset_key=asset_key,
            partition_key=trade_date,
            check_name=check_names[0],
            passed=True,
            scope=CheckScope.SCHEMA,
            checked_row_count=int(silver_row["formal_silver_row_count"]),
            failed_row_count=0,
            file_path=silver_path,
            extra_metadata={
                **common,
                "silver_sha256": silver_row["formal_silver_sha256"],
                "summary": "ETF 分钟 Silver 文件合同已由 Bootstrap 验收。",
            },
        ),
        _make_etf_mins_check_spec(
            evidence=evidence,
            asset_key=asset_key,
            partition_key=trade_date,
            check_name=check_names[1],
            passed=True,
            scope=CheckScope.RECONCILIATION,
            checked_row_count=int(silver_row["formal_silver_row_count"]),
            failed_row_count=0,
            file_path=silver_path,
            extra_metadata={
                **common,
                "raw_uri": str(raw_path),
                "raw_sha256": raw_row["formal_raw_sha256"],
                "silver_sha256": silver_row["formal_silver_sha256"],
                "summary": "ETF 分钟 Silver 与 Raw 双向等价已由 Bootstrap 验收。",
            },
        ),
    )


def _make_etf_mins_check_spec(
    *,
    evidence: _EtfMinsBootstrapPhysicalEvidence,
    asset_key: dg.AssetKey,
    partition_key: str,
    check_name: str,
    passed: bool,
    scope: CheckScope,
    checked_row_count: int,
    failed_row_count: int,
    file_path: Path,
    extra_metadata: Mapping[str, object],
) -> _EtfMinsCheckEventSpec:
    identity = {
        "event_kind": "etf_mins_bootstrap_check",
        "operation_id": evidence.report.operation_id,
        "plan_fingerprint": evidence.report.plan_fingerprint,
        "physical_final_report_hash": evidence.report.report_hash,
        "asset_key": asset_key.to_user_string(),
        "partition_key": partition_key,
        "check_name": check_name,
        "passed": passed,
        "scope": scope.value,
        "checked_row_count": checked_row_count,
        "failed_row_count": failed_row_count,
        "evidence": dict(extra_metadata),
    }
    metadata = build_check_metadata(
        check_scope=scope,
        checked_row_count=checked_row_count,
        failed_row_count=failed_row_count,
        file_path=file_path,
        extra_metadata={
            **dict(extra_metadata),
            "event_identity_hash": compute_etf_mins_bootstrap_payload_hash(identity),
        },
    )
    return _EtfMinsCheckEventSpec(
        asset_key=asset_key,
        partition_key=partition_key,
        check_name=check_name,
        passed=passed,
        metadata=metadata,
    )


def _decision_reason_codes(row: Mapping[str, object]) -> tuple[str, ...]:
    try:
        value = json.loads(str(row["decision_reason_codes_json"]))
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_event_decision_reasons_invalid."
        ) from error
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise EtfMinsBootstrapError(
            "etf_mins_bootstrap_event_decision_reasons_invalid."
        )
    return tuple(value)


def _decision_issue_counts(row: Mapping[str, object]) -> dict[str, int]:
    reason_codes = (
        *ETF_MINS_RAW_OBSERVATION_REASON_CODES,
        "full_zero_volume_etf_day_observed",
        "minute_grid_contract_anomaly",
    )
    return {
        reason_code: int(row.get(f"{reason_code}_count", 0))
        for reason_code in reason_codes
        if int(row.get(f"{reason_code}_count", 0)) > 0
    }


def _load_latest_etf_mins_materializations(
    *,
    instance: dg.DagsterInstance,
    specs: Sequence[_EtfMinsMaterializationEventSpec],
) -> tuple[dict[tuple[str, str], object], int]:
    by_asset: dict[str, tuple[dg.AssetKey, set[str]]] = {}
    for spec in specs:
        name = spec.asset_key.to_user_string()
        if name not in by_asset:
            by_asset[name] = (spec.asset_key, set())
        by_asset[name][1].add(spec.partition_key)
    result: dict[tuple[str, str], object] = {}
    for asset_name, (asset_key, partitions) in by_asset.items():
        limit = max(1_000, len(partitions) * 4)
        records = instance.fetch_materializations(
            dg.AssetRecordsFilter(
                asset_key=asset_key,
                asset_partitions=sorted(partitions),
            ),
            limit=limit,
        ).records
        for record in records:
            partition = str(getattr(record, "partition_key", "") or "")
            if partition in partitions:
                result.setdefault((asset_name, partition), record)
        if len(records) == limit and any(
            (asset_name, partition) not in result for partition in partitions
        ):
            raise EtfMinsBootstrapError(
                "etf_mins_bootstrap_materialization_history_truncated."
            )
    return result, len(by_asset)


def _load_latest_etf_mins_checks(
    *,
    instance: dg.DagsterInstance,
    specs: Sequence[_EtfMinsCheckEventSpec],
) -> tuple[dict[tuple[str, str, str], object], int]:
    grouped: dict[tuple[str, str], tuple[dg.AssetKey, set[str]]] = {}
    for spec in specs:
        key = (spec.asset_key.to_user_string(), spec.check_name)
        if key not in grouped:
            grouped[key] = (spec.asset_key, set())
        grouped[key][1].add(spec.partition_key)
    result: dict[tuple[str, str, str], object] = {}
    for (asset_name, check_name), (asset_key, partitions) in grouped.items():
        limit = max(500, len(partitions) * 10)
        records = instance.event_log_storage.get_asset_check_execution_history(
            dg.AssetCheckKey(asset_key, check_name),
            limit=limit,
        )
        for record in records:
            partition = str(getattr(record, "partition", "") or "")
            if partition in partitions:
                result.setdefault((asset_name, check_name, partition), record)
        if len(records) == limit and any(
            (asset_name, check_name, partition) not in result
            for partition in partitions
        ):
            raise EtfMinsBootstrapError("etf_mins_bootstrap_check_history_truncated.")
    return result, len(grouped)


def _materialization_spec_key(
    spec: _EtfMinsMaterializationEventSpec,
) -> tuple[str, str]:
    return spec.asset_key.to_user_string(), spec.partition_key


def _check_materialization_key(spec: _EtfMinsCheckEventSpec) -> tuple[str, str]:
    return spec.asset_key.to_user_string(), spec.partition_key


def _check_spec_key(spec: _EtfMinsCheckEventSpec) -> tuple[str, str, str]:
    return spec.asset_key.to_user_string(), spec.check_name, spec.partition_key


def _materialization_record_matches(
    record: object,
    spec: _EtfMinsMaterializationEventSpec,
) -> bool:
    materialization = getattr(record, "asset_materialization", None)
    if materialization is None:
        return False
    return _metadata_contains(materialization.metadata, spec.metadata)


def _check_record_matches(
    record: object,
    spec: _EtfMinsCheckEventSpec,
    *,
    target_storage_id: int,
) -> bool:
    event = getattr(record, "event", None)
    dagster_event = getattr(event, "dagster_event", None) if event else None
    evaluation = (
        getattr(dagster_event, "event_specific_data", None)
        if dagster_event is not None
        else None
    )
    target = getattr(evaluation, "target_materialization_data", None)
    return bool(
        evaluation is not None
        and bool(getattr(evaluation, "passed", False)) is spec.passed
        and bool(getattr(evaluation, "blocking", False))
        and target is not None
        and int(target.storage_id) == target_storage_id
        and _metadata_contains(getattr(evaluation, "metadata", {}), spec.metadata)
    )


def _metadata_contains(
    actual: Mapping[str, object],
    expected: Mapping[str, object],
) -> bool:
    return all(
        _metadata_scalar(actual.get(key)) == _metadata_scalar(value)
        for key, value in expected.items()
    )


def _metadata_scalar(value: object) -> object:
    scalar = getattr(value, "value", value)
    if isinstance(scalar, Mapping):
        return {
            str(key): _metadata_scalar(item)
            for key, item in sorted(scalar.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(scalar, (list, tuple)):
        return tuple(_metadata_scalar(item) for item in scalar)
    return scalar


def _recent_etf_mins_check_trade_dates(
    trade_dates: Sequence[str],
) -> tuple[str, ...]:
    return tuple(trade_dates[-_ETF_MINS_EVENT_CHECK_WINDOW:])


def _sample_etf_mins_trade_dates(trade_dates: Sequence[str]) -> tuple[str, ...]:
    if not trade_dates:
        return ()
    indices = (0, len(trade_dates) // 2, len(trade_dates) - 1)
    return tuple(dict.fromkeys(trade_dates[index] for index in indices))


__all__ = [
    "ETF_MINS_BOOTSTRAP_KIND",
    "ETF_MINS_BOOTSTRAP_PROTECTION_2026",
    "ETF_MINS_BOOTSTRAP_PROTECTION_NOT_APPLICABLE",
    "ETF_MINS_BOOTSTRAP_SCHEMA_VERSION",
    "EtfMinsBootstrapError",
    "EtfMinsBootstrapEventReport",
    "EtfMinsBootstrapPartitionReport",
    "EtfMinsBootstrapPlan",
    "EtfMinsBootstrapRawApplyReport",
    "EtfMinsBootstrapRawEvidence",
    "EtfMinsBootstrapSilverApplyReport",
    "apply_etf_mins_bootstrap_events",
    "apply_etf_mins_bootstrap_raw",
    "apply_etf_mins_bootstrap_silver",
    "audit_etf_mins_bootstrap_events",
    "audit_etf_mins_bootstrap_targets",
    "build_etf_mins_bootstrap_plan",
    "compute_etf_mins_bootstrap_manifest_hash",
    "compute_etf_mins_bootstrap_payload_hash",
    "load_etf_mins_bootstrap_plan",
    "load_etf_mins_bootstrap_raw_evidence",
    "load_etf_mins_bootstrap_trade_dates",
    "operation_root_for_etf_mins_bootstrap",
    "plan_etf_mins_bootstrap_events",
    "plan_etf_mins_bootstrap_partitions",
    "register_etf_mins_bootstrap_partitions",
    "run_etf_mins_bootstrap_plan",
    "validate_etf_mins_bootstrap_operation_path",
    "write_etf_mins_bootstrap_plan",
]
