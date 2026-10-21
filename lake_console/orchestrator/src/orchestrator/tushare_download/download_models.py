"""Immutable public values and explicitly owned, private request counters."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import IntEnum
from typing import Protocol

from .download_errors import DownloadErrorCode, ErrorDetails

SourceScalar = bool | int | Decimal | str | None


class DownloadMode(IntEnum):
    SNAPSHOT = 1
    BY_POINT = 2
    BY_OBJECT = 3
    BY_OBJECT_POINT = 4
    BY_OBJECT_RANGE = 5
    BY_RANGE = 6


class DownloadStatus(IntEnum):
    CREATED = 1
    READY = 2
    RUNNING = 3
    SUCCEEDED = 4
    STOPPED = 5
    CANCELLED = 6
    FAILED = 7


class DownloadStage(IntEnum):
    PREPARE = 1
    SOURCE = 2
    BACKOFF = 3
    ORDERING = 4
    UNIT_READY = 5
    CLOSE = 6


class DownloadProgressEvent(IntEnum):
    PAGE_COMPLETED = 1
    RETRY_SCHEDULED = 2
    UNIT_COMPLETED = 3


@dataclass(frozen=True, slots=True)
class TimeRange:
    start: str
    end: str


@dataclass(frozen=True, slots=True)
class ObjectTimeRange:
    object_code: str
    time_range: TimeRange


@dataclass(frozen=True, slots=True)
class DownloadTask:
    contract_name: str
    mode: DownloadMode
    objects: tuple[str, ...] | None = None
    points: tuple[str, ...] | None = None
    time_range: TimeRange | None = None
    object_ranges: tuple[ObjectTimeRange, ...] | None = None
    filters: Mapping[str, SourceScalar] | None = None
    enum_values: Mapping[str, tuple[SourceScalar, ...]] | None = None


@dataclass(frozen=True, slots=True)
class DownloadControl:
    is_cancelled: Callable[[], bool] | None = None


@dataclass(frozen=True, slots=True)
class DownloadScope:
    object_code: str | None = None
    point: str | None = None
    time_range: TimeRange | None = None
    request_input_index: int | None = None


@dataclass(frozen=True, slots=True)
class PagePosition:
    request_input_index: int
    time_range: TimeRange | None = None
    offset: int | None = None


@dataclass(frozen=True, slots=True)
class DownloadUnit:
    ordinal: int
    unit_id: str
    contract_name: str
    contract_version: str
    content_digest: str
    mode: DownloadMode
    object_code: str | None
    point: str | None
    time_range: TimeRange | None
    filters: tuple[tuple[str, SourceScalar], ...]
    enum_values: tuple[tuple[str, tuple[SourceScalar, ...]], ...]


@dataclass(frozen=True, slots=True)
class SourceRecord:
    fields: tuple[str, ...]
    values: tuple[SourceScalar, ...]
    request_input_index: int

    def as_mapping(self) -> dict[str, SourceScalar]:
        return dict(zip(self.fields, self.values, strict=True))


@dataclass(frozen=True, slots=True)
class PageRequest:
    api_name: str
    fields: tuple[str, ...]
    params: tuple[tuple[str, SourceScalar], ...]
    position: PagePosition
    expected_limit: int | None


@dataclass(frozen=True, slots=True)
class SourcePage:
    fields: tuple[str, ...]
    records: tuple[SourceRecord, ...]
    total: int | None = None
    next_offset: int | None = None


@dataclass(frozen=True, slots=True)
class CleanupIssue:
    owner: str
    cause_type: str


@dataclass(frozen=True, slots=True)
class AttemptFailure:
    code: DownloadErrorCode
    source_status: int | None = None
    source_code: int | None = None
    cause_type: str | None = None
    retry_after_at: float | None = None
    cleanup_errors: tuple[CleanupIssue, ...] = ()


@dataclass(frozen=True, slots=True)
class AttemptOutcome:
    page: SourcePage | None = None
    failure: AttemptFailure | None = None

    def __post_init__(self):
        if (self.page is None) == (self.failure is None):
            raise ValueError("exactly one attempt outcome is required")


@dataclass(frozen=True, slots=True)
class UnitStatistics:
    request_count: int
    retry_count: int
    successful_response_count: int
    accepted_page_count: int
    empty_page_count: int
    row_count: int
    split_count: int
    elapsed_seconds: float
    waiting_seconds: float
    receive_seconds: float
    sort_seconds: float


@dataclass(frozen=True, slots=True)
class OrderingFacts:
    time_field: str | None
    rule_version: str
    comparable_count: int
    uncomparable_count: int


@dataclass(frozen=True, slots=True)
class TerminationSummary:
    strategy: int
    all_scopes_complete: bool
    accepted_scope_count: int
    last_position: PagePosition | None


@dataclass(frozen=True, slots=True)
class UnitResult:
    unit: DownloadUnit
    records: tuple[SourceRecord, ...]
    observed_field_sets: tuple[tuple[str, ...], ...]
    request_inputs: tuple[tuple[tuple[str, SourceScalar], ...], ...]
    statistics: UnitStatistics
    ordering: OrderingFacts
    termination: TerminationSummary


@dataclass(frozen=True, slots=True)
class DownloadProgress:
    notification_version: int
    event: DownloadProgressEvent
    sequence: int
    task_id: str
    contract_name: str
    current_unit_id: str
    unit_ordinal: int
    stage: DownloadStage
    current_scope: DownloadScope
    page_position: PagePosition | None
    total_units: int
    completed_units: int
    delivered_units: int
    progress_percent: float | None
    unit_row_count: int
    completed_row_count: int
    page_row_count: int | None
    page_accepted: bool | None
    request_count: int
    retry_count: int
    attempt_number: int | None
    next_attempt_number: int | None
    retry_delay_seconds: float | None
    error_code: DownloadErrorCode | None
    elapsed_seconds: float
    updated_at: str
    cancel_requested: bool


ProgressCallback = Callable[[DownloadProgress], None]


@dataclass(frozen=True, slots=True)
class DownloadSummary:
    task_id: str
    status: DownloadStatus
    total_units: int | None
    completed_units: int
    delivered_units: int
    completed_row_count: int
    row_count: int
    request_count: int
    retry_count: int
    successful_response_count: int
    download_complete: bool
    elapsed_seconds: float
    failure: ErrorDetails | None
    cleanup_errors: tuple[CleanupIssue, ...]
    progress_error_count: int
    last_progress_error_type: str | None
    callback_elapsed_seconds: float


@dataclass(slots=True)
class SessionCounters:
    completed_units: int = 0
    delivered_units: int = 0
    completed_row_count: int = 0
    row_count: int = 0
    request_count: int = 0
    retry_count: int = 0
    successful_response_count: int = 0
    progress_error_count: int = 0
    last_progress_error_type: str | None = None
    callback_elapsed_seconds: float = 0.0


@dataclass(slots=True)
class UnitCounters:
    request_count: int = 0
    retry_count: int = 0
    successful_response_count: int = 0
    accepted_page_count: int = 0
    empty_page_count: int = 0
    row_count: int = 0
    split_count: int = 0
    waiting_seconds: float = 0.0
    receive_seconds: float = 0.0
    sort_seconds: float = 0.0


@dataclass(slots=True)
class RequestCounters:
    session: SessionCounters
    unit: UnitCounters

    def mark_sent(self, attempt_number: int) -> None:
        for counters in (self.session, self.unit):
            counters.request_count += 1
            counters.retry_count += int(attempt_number > 1)

    def mark_response_success(self) -> None:
        self.session.successful_response_count += 1
        self.unit.successful_response_count += 1


@dataclass(slots=True)
class CompletedUnitBuffer:
    unit: DownloadUnit
    counters: UnitCounters
    started_at: float
    request_inputs: tuple[tuple[tuple[str, SourceScalar], ...], ...] = ()
    records: list[SourceRecord] = field(default_factory=list)
    field_sets: dict[tuple[str, ...], tuple[str, ...]] = field(default_factory=dict)
    termination: TerminationSummary | None = None

    def clear(self) -> None:
        self.records.clear()
        self.field_sets.clear()
        self.request_inputs = ()


@dataclass(frozen=True, slots=True)
class ProgressFacts:
    unit: DownloadUnit
    unit_row_count: int
    position: PagePosition | None = None
    attempt_number: int | None = None
    page_row_count: int | None = None
    page_accepted: bool | None = None
    next_attempt_number: int | None = None
    retry_delay_seconds: float | None = None
    error_code: DownloadErrorCode | None = None


class Control(Protocol):
    def raise_if_cancelled(self) -> None: ...
    def set_location(self, stage, unit_id, position, attempt_number) -> None: ...
    def error_location(self) -> ErrorDetails: ...


class Clock(Protocol):
    def monotonic(self) -> float: ...
    def utc_now(self): ...
