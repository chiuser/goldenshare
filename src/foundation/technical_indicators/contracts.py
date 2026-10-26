"""Immutable request and result contracts, independent of storage and HTTP."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime
import math
import re
from types import MappingProxyType
from typing import Literal, TYPE_CHECKING
from zoneinfo import ZoneInfo

from .errors import RequestInvalidError, ResourceLimitError

if TYPE_CHECKING:
    from .configuration.settings import KernelConfig

SecurityType = Literal["stock", "index"]
Period = Literal["1m", "5m", "15m", "30m", "60m", "90m", "120m", "day", "week", "month"]
Adjustment = Literal["none", "qfq", "hfq"]
TimePosition = date | datetime
ParameterValue = int | float | str | bool | None
Parameters = tuple[tuple[str, int | float], ...]
PERIODS: tuple[Period, ...] = ("1m", "5m", "15m", "30m", "60m", "90m", "120m", "day", "week", "month")
TIMEZONE = "Asia/Shanghai"
KERNEL_VERSION = "2.0.0"
_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_SECURITY = re.compile(r"[0-9]{6}\.(?:SH|SZ|BJ)\Z")


def _freeze_parameters(values) -> Parameters:
    """Copy the two declared container levels; parameter scalars are immutable."""
    if not isinstance(values, (tuple, list)):
        raise RequestInvalidError("Parameters require a sequence of name/value pairs")
    copied = []
    for item in values:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise RequestInvalidError("Parameters require name/value pairs")
        name, value = item
        if not isinstance(name, str) or type(value) not in (int, float):
            raise RequestInvalidError("Normalized parameters require names and numeric scalars")
        copied.append((name, value))
    return tuple(copied)


@dataclass(frozen=True, slots=True)
class CalculationInstance:
    instance_id: str
    calculation_id: str
    parameters: Mapping[str, ParameterValue]

    def __post_init__(self) -> None:
        for value in (self.instance_id, self.calculation_id):
            if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
                raise RequestInvalidError("Calculation identifiers require 1–64 letters, digits, '_' or '-'")
        if not isinstance(self.parameters, Mapping):
            raise RequestInvalidError("parameters must be a mapping")
        copied = dict(self.parameters)
        for name, value in copied.items():
            if not isinstance(name, str) or not isinstance(value, (int, float, str, bool, type(None))):
                raise RequestInvalidError("parameters require named JSON scalar values")
            if isinstance(value, float) and not math.isfinite(value):
                raise RequestInvalidError("parameters must be finite")
        object.__setattr__(self, "parameters", MappingProxyType(copied))


@dataclass(frozen=True, slots=True)
class CalculationRequest:
    security_type: SecurityType
    ts_code: str
    period: Period
    calculations: tuple[CalculationInstance, ...]
    adjustment: Adjustment = "qfq"
    start: TimePosition | None = None
    end: TimePosition | None = None
    limit: int = 1000
    before: TimePosition | None = None

    def __post_init__(self) -> None:
        if self.security_type not in ("stock", "index"):
            raise RequestInvalidError("Unsupported security_type")
        if not isinstance(self.ts_code, str) or _SECURITY.fullmatch(self.ts_code) is None:
            raise RequestInvalidError("ts_code must be a six-digit code with SH, SZ or BJ suffix")
        if self.period not in PERIODS:
            raise RequestInvalidError("Unsupported period")
        if self.adjustment not in ("none", "qfq", "hfq"):
            raise RequestInvalidError("One target adjustment is required")
        if type(self.limit) is not int or self.limit <= 0:
            raise RequestInvalidError("limit must be a positive integer")
        if not isinstance(self.calculations, (tuple, list)) or not self.calculations:
            raise RequestInvalidError("At least one calculation instance is required")
        instances = tuple(self.calculations)
        if not all(isinstance(item, CalculationInstance) for item in instances):
            raise RequestInvalidError("calculations must contain CalculationInstance objects")
        if len({item.instance_id for item in instances}) != len(instances):
            raise RequestInvalidError("Duplicate instance_id")
        object.__setattr__(self, "calculations", instances)
        minute = self.period.endswith("m")
        for name in ("start", "end", "before"):
            value = getattr(self, name)
            if value is None:
                continue
            if minute:
                if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
                    raise RequestInvalidError("Minute ranges require timezone-aware datetime")
                object.__setattr__(self, name, value.astimezone(ZoneInfo(TIMEZONE)))
            elif type(value) is not date:
                raise RequestInvalidError("Day/week/month ranges require date, not datetime")
        if self.start is not None and self.end is not None and self.start > self.end:
            raise RequestInvalidError("start must not exceed end")


def normalize_request_and_validate_all_instances(
    request: CalculationRequest, config: KernelConfig,
) -> CalculationRequest:
    """Validate the structural request before registry parameters or any I/O."""
    if not isinstance(request, CalculationRequest):
        raise RequestInvalidError("A CalculationRequest is required")
    normalized = replace(request)
    if normalized.limit > config.max_output_rows:
        raise ResourceLimitError("Requested output positions exceed max_output_rows")
    if len(normalized.calculations) > config.max_indicator_instances:
        raise ResourceLimitError("Calculation instances exceed max_indicator_instances")
    return normalized


@dataclass(frozen=True, slots=True)
class SeriesDescription:
    security_type: SecurityType
    ts_code: str
    period: Period
    adjustment: Adjustment
    timezone: str
    price_unit: str
    volume_unit: str
    amount_unit: str


@dataclass(frozen=True, slots=True)
class RequestedRange:
    start: TimePosition | None
    end: TimePosition | None
    before: TimePosition | None
    limit: int


@dataclass(frozen=True, slots=True)
class SourceResult:
    id: str
    contract_version: str
    input_adjustment: Adjustment
    history_start: TimePosition | None
    read_start: TimePosition | None
    read_end: TimePosition | None
    available_through: TimePosition | None


@dataclass(frozen=True, slots=True)
class PriceAdjustmentResult:
    input_basis_rule: str | None
    output_basis_rule: str | None
    basis_date: date | None
    basis_value: float | None
    converted: bool
    formula_version: str


@dataclass(frozen=True, slots=True)
class CalculationValues:
    instance_id: str
    calculation_id: str
    algorithm_version: str
    parameters: Parameters
    fields: tuple[tuple[str, tuple[float | None, ...]], ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", _freeze_parameters(self.parameters))
        object.__setattr__(self, "fields", tuple((name, tuple(values)) for name, values in self.fields))


@dataclass(frozen=True, slots=True)
class OutputRange:
    actual_start: TimePosition | None
    actual_end: TimePosition | None
    count: int


@dataclass(frozen=True, slots=True)
class CalculationStatistics:
    source_rows: int
    sql_processed_rows: int
    source_files: int
    source_file_bytes: int
    locator_rows: int
    price_conversion_batches: int
    elapsed_ms: float


@dataclass(frozen=True, slots=True)
class CalculationResult:
    kernel_version: str
    series: SeriesDescription
    requested: RequestedRange
    source: SourceResult
    price_adjustment: PriceAdjustmentResult
    times: tuple[TimePosition, ...]
    source_as_of: tuple[date, ...] | None
    calculations: tuple[CalculationValues, ...]
    range: OutputRange
    statistics: CalculationStatistics
    msg: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "times", tuple(self.times))
        object.__setattr__(self, "calculations", tuple(self.calculations))
        if self.source_as_of is not None:
            object.__setattr__(self, "source_as_of", tuple(self.source_as_of))
