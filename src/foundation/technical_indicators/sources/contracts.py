"""Data-source handoffs only; no reader, connection or quality audit."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol, TYPE_CHECKING

from ..contracts import Adjustment, CalculationRequest, TimePosition
from ..calculation.history import HistoryRequirement

if TYPE_CHECKING:
    from ..execution_control import ExecutionControl
    from ..executor import DuckDBExecutor


@dataclass(frozen=True, slots=True)
class SourceDescription:
    source_id: str
    contract_version: str
    input_adjustment: Adjustment
    basis_rule: str | None
    basis_date: date | None
    basis_value: float | None
    price_unit: str
    volume_unit: str
    amount_unit: str
    timezone: str
    period_label_rule: str
    history_origin_rule: str
    available_through: TimePosition | None
    supports_partial_period: bool
    supported_adjustment_paths: tuple[tuple[Adjustment, Adjustment], ...]
    converted: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "supported_adjustment_paths", tuple(tuple(item) for item in self.supported_adjustment_paths))


@dataclass(frozen=True, slots=True)
class ReadRequirement:
    request: CalculationRequest
    history: HistoryRequirement
    batch_rows: int
    history_start: TimePosition | None
    processing_end: TimePosition | None


@dataclass(frozen=True, slots=True)
class SourceBatch:
    columns: object
    source_first_position: int
    source_last_position: int
    physical_rows: int
    selected_rows: int
    source_files: int
    source_file_bytes: int


@dataclass(frozen=True, slots=True)
class PriceBatch:
    table_name: str
    new_first_seq: int
    new_last_seq: int
    new_row_count: int
    history_rows: int
    time_fields: tuple[str, ...]
    fields: tuple[str, ...]
    adjustment: Adjustment

    def __post_init__(self) -> None:
        object.__setattr__(self, "time_fields", tuple(self.time_fields))
        object.__setattr__(self, "fields", tuple(self.fields))


class SourceStream(Protocol):
    def next_batch(self, max_rows: int) -> SourceBatch | None: ...
    def release_current_batch(self) -> None: ...
    def close(self) -> None: ...


class PriceSource(Protocol):
    def describe(
        self, request: CalculationRequest, requirement: ReadRequirement, *, control: ExecutionControl,
    ) -> SourceDescription: ...

    def open(
        self, executor: DuckDBExecutor, description: SourceDescription, requirement: ReadRequirement,
    ) -> SourceStream: ...
