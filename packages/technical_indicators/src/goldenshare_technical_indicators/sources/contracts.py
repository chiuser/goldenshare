"""Data-source handoffs only; no reader, connection or quality audit."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol, TYPE_CHECKING

from ..contracts import Adjustment, CalculationRequest, TimePosition
from ..calculation.history import HistoryRequirement

if TYPE_CHECKING:
    from ..execution_control import ExecutionControl
    from ..executor import DuckDBExecutor
    from .read_context import SourceReadContext


@dataclass(frozen=True, slots=True)
class PriceReadSelection:
    target_start: TimePosition | None
    target_end: TimePosition | None
    read_start: TimePosition | None
    read_end: TimePosition | None
    target_rows: int
    preceding_rows: int
    reached_source_origin: bool
    row_groups: tuple[tuple[int, ...], ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "row_groups", tuple(tuple(group) for group in self.row_groups))
        if (type(self.target_rows) is not int or self.target_rows < 0
                or type(self.preceding_rows) is not int or self.preceding_rows < 0
                or type(self.reached_source_origin) is not bool):
            raise ValueError("Selection counts and source-origin flag have invalid types")
        for group in self.row_groups:
            if (not group or any(type(i) is not int or i < 0 for i in group)
                    or tuple(sorted(set(group))) != group):
                raise ValueError("Selected row groups must be nonempty, ordered and unique")
        positions = (self.target_start, self.target_end, self.read_start, self.read_end)
        if self.target_rows == 0:
            if self.preceding_rows or any(p is not None for p in positions) or self.row_groups:
                raise ValueError("An empty target cannot carry price input")
        elif (any(p is None for p in positions)
                or not self.read_start <= self.target_start <= self.target_end == self.read_end):
            raise ValueError("Selected input and target ranges are inconsistent")


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
    selection: PriceReadSelection
    price_paths: tuple[Path, ...] = ()
    factor_paths: tuple[tuple[date, Path], ...] = ()
    source_projection: tuple[str, ...] = ()
    standard_projection: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "supported_adjustment_paths", tuple(tuple(item) for item in self.supported_adjustment_paths))
        object.__setattr__(self, "price_paths", tuple(Path(item) for item in self.price_paths))
        object.__setattr__(self, "factor_paths", tuple((day, Path(path)) for day, path in self.factor_paths))
        object.__setattr__(self, "source_projection", tuple(self.source_projection))
        object.__setattr__(self, "standard_projection", tuple(tuple(item) for item in self.standard_projection))
        if not isinstance(self.selection, PriceReadSelection) or len(self.price_paths) != len(self.selection.row_groups):
            raise ValueError("Selected price paths and row groups must correspond")


@dataclass(frozen=True, slots=True)
class ReadRequirement:
    request: CalculationRequest
    history: HistoryRequirement
    batch_rows: int
    history_start: TimePosition | None
    processing_end: TimePosition | None


@dataclass(frozen=True, slots=True)
class SourceBatch:
    """One compact, coalesced RecordBatch; positions count deliveries, not reads."""

    columns: object
    source_first_position: int
    source_last_position: int
    physical_rows: int | None
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
    """Fill max_rows across files, except the final source batch.

    Release only the delivery; a previously read remainder belongs to this
    stream until the next delivery or close. No file boundary ends a batch.
    """

    def next_batch(self, max_rows: int) -> SourceBatch | None: ...
    def release_current_batch(self) -> None: ...
    def close(self) -> None: ...


class SourceLocator(Protocol):
    def describe(self) -> SourceDescription: ...
    def close(self) -> None: ...


class PriceSource(Protocol):
    def create_locator(
        self, executor: DuckDBExecutor, requirement: ReadRequirement, *,
        read_context: SourceReadContext,
    ) -> SourceLocator: ...

    def open(
        self, executor: DuckDBExecutor, description: SourceDescription, requirement: ReadRequirement,
        *, read_context: SourceReadContext,
    ) -> SourceStream: ...

    def prepare_basis(
        self, executor: DuckDBExecutor, description: SourceDescription, requirement: ReadRequirement,
        *, table_name: str, read_context: SourceReadContext,
    ) -> SourceDescription: ...

    def prepare_factors(
        self, executor: DuckDBExecutor, description: SourceDescription, requirement: ReadRequirement,
        trade_dates: tuple[date, ...], *, table_name: str, read_context: SourceReadContext,
    ) -> None: ...
