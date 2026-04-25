from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable


RunProfile = str
DateAnchorPolicy = str
PaginationPolicy = str
WindowPolicy = str


@dataclass(slots=True, frozen=True)
class DatasetDateModel:
    date_axis: str
    bucket_rule: str
    window_mode: str
    input_shape: str
    observed_field: str | None
    audit_applicable: bool
    not_applicable_reason: str | None = None


@dataclass(slots=True, frozen=True)
class InputField:
    name: str
    field_type: str
    required: bool = False
    default: Any = None
    enum_values: tuple[str, ...] = ()
    allow_empty: bool = False
    description: str = ""


@dataclass(slots=True, frozen=True)
class InputSchema:
    fields: tuple[InputField, ...]
    required_groups: tuple[tuple[str, ...], ...] = ()
    mutually_exclusive_groups: tuple[tuple[str, ...], ...] = ()
    dependencies: tuple[tuple[str, str], ...] = ()


@dataclass(slots=True, frozen=True)
class PlanningSpec:
    universe_policy: str = "none"
    enum_fanout_fields: tuple[str, ...] = ()
    enum_fanout_defaults: dict[str, tuple[str, ...]] = field(default_factory=dict)
    pagination_policy: PaginationPolicy = "none"
    chunk_size: int | None = None
    max_units_per_execution: int | None = None


@dataclass(slots=True, frozen=True)
class SourceSpec:
    api_name: str
    fields: tuple[str, ...]
    unit_params_builder: Callable[
        ["ValidatedRunRequest", date | None, dict[str, Any]],
        dict[str, Any],
    ]
    source_key_default: str = "tushare"
    base_params: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class NormalizationSpec:
    date_fields: tuple[str, ...] = ()
    decimal_fields: tuple[str, ...] = ()
    required_fields: tuple[str, ...] = ()
    row_transform: Callable[[dict[str, Any]], dict[str, Any]] | None = None


@dataclass(slots=True, frozen=True)
class WriteSpec:
    raw_dao_name: str
    core_dao_name: str
    target_table: str
    conflict_columns: tuple[str, ...] | None = None
    write_path: str = "raw_core_upsert"


@dataclass(slots=True, frozen=True)
class ObserveSpec:
    progress_label: str


@dataclass(slots=True, frozen=True)
class RateLimitSpec:
    max_retries: int = 3
    retry_backoff_seconds: float = 0.5


@dataclass(slots=True, frozen=True)
class PaginationSpec:
    page_limit: int | None = None


@dataclass(slots=True, frozen=True)
class DatasetSyncContract:
    dataset_key: str
    display_name: str
    job_name: str
    run_profiles_supported: tuple[RunProfile, ...]
    date_model: DatasetDateModel
    input_schema: InputSchema
    planning_spec: PlanningSpec
    source_adapter_key: str
    source_spec: SourceSpec
    normalization_spec: NormalizationSpec
    write_spec: WriteSpec
    observe_spec: ObserveSpec
    rate_limit_spec: RateLimitSpec = field(default_factory=RateLimitSpec)
    pagination_spec: PaginationSpec = field(default_factory=PaginationSpec)


@dataclass(slots=True, frozen=True)
class RunRequest:
    request_id: str
    dataset_key: str
    run_profile: RunProfile
    trigger_source: str
    params: dict[str, Any] = field(default_factory=dict)
    source_key: str | None = None
    trade_date: date | None = None
    start_date: date | None = None
    end_date: date | None = None
    correlation_id: str | None = None
    rerun_id: str | None = None
    execution_id: int | None = None


@dataclass(slots=True, frozen=True)
class ValidatedRunRequest:
    request_id: str
    dataset_key: str
    run_profile: RunProfile
    trigger_source: str
    params: dict[str, Any]
    source_key: str | None
    trade_date: date | None
    start_date: date | None
    end_date: date | None
    correlation_id: str
    rerun_id: str | None
    execution_id: int | None
    validated_at: datetime


@dataclass(slots=True, frozen=True)
class PlanUnit:
    unit_id: str
    dataset_key: str
    source_key: str
    trade_date: date | None
    request_params: dict[str, Any]
    progress_context: dict[str, Any] = field(default_factory=dict)
    pagination_policy: str | None = None
    page_limit: int | None = None
    attempt: int = 0
    priority: int = 0
    requested_source_key: str | None = None


@dataclass(slots=True, frozen=True)
class FetchResult:
    unit_id: str
    request_count: int
    retry_count: int
    latency_ms: int
    rows_raw: list[dict[str, Any]]
    source_http_status: int | None = None


@dataclass(slots=True, frozen=True)
class NormalizedBatch:
    unit_id: str
    rows_normalized: list[dict[str, Any]]
    rows_rejected: int
    rejected_reasons: dict[str, int]


@dataclass(slots=True, frozen=True)
class WriteResult:
    unit_id: str
    rows_written: int
    rows_upserted: int
    rows_skipped: int
    target_table: str
    conflict_strategy: str


@dataclass(slots=True, frozen=True)
class EngineRunSummary:
    dataset_key: str
    run_profile: str
    unit_total: int
    unit_done: int
    unit_failed: int
    rows_fetched: int
    rows_written: int
    rows_rejected: int
    rejected_reason_counts: dict[str, int]
    result_date: date | None
    message: str | None
    error_counts: dict[str, int]


def resolve_contract_anchor_type(contract: DatasetSyncContract) -> DateAnchorPolicy:
    date_model = contract.date_model
    if date_model.date_axis == "trade_open_day":
        if date_model.bucket_rule == "week_last_open_day":
            return "week_end_trade_date"
        if date_model.bucket_rule == "month_last_open_day":
            return "month_end_trade_date"
        return "trade_date"
    if date_model.date_axis == "natural_day":
        return "natural_date_range"
    if date_model.date_axis == "month_key":
        return "month_key_yyyymm"
    if date_model.date_axis == "month_window":
        return "month_range_natural"
    return "none"


def resolve_contract_window_policy(contract: DatasetSyncContract) -> WindowPolicy:
    return str(contract.date_model.window_mode or "none").strip() or "none"
