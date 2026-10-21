"""Pure source definitions and explicitly registered time rules; no storage schema."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import IntEnum
from zoneinfo import ZoneInfo

from .download_errors import DownloadErrorCode, require
from .download_models import DownloadMode, SourceScalar, TimeRange


class SourceKind(IntEnum):
    STRING = 1
    INTEGER = 2
    NUMBER = 3
    BOOLEAN = 4


def valid_scalar(value) -> bool:
    return (
        value is None
        or type(value) in (str, bool, int)
        or (type(value) is Decimal and value.is_finite())
    )


def scalar_matches(value, kind: SourceKind, nullable: bool = False) -> bool:
    if value is None:
        return nullable
    return {
        SourceKind.STRING: type(value) is str,
        SourceKind.INTEGER: type(value) is int,
        SourceKind.NUMBER: type(value) in (int, Decimal) and valid_scalar(value),
        SourceKind.BOOLEAN: type(value) is bool,
    }.get(kind, False)


@dataclass(frozen=True, slots=True)
class SourceField:
    name: str
    source_kind: SourceKind
    format: str = ""
    description: str = ""
    nullable: bool = True
    precision_note: str = ""


@dataclass(frozen=True, slots=True)
class ParameterRule:
    name: str
    source_kind: SourceKind
    required: bool = False
    has_default: bool = False
    default: SourceScalar = None
    nullable: bool = False
    choices: tuple[SourceScalar, ...] | None = None


@dataclass(frozen=True, slots=True)
class EnumRule:
    parameter_name: str
    ordered_values: tuple[SourceScalar, ...]
    has_default: bool = False
    default_values: tuple[SourceScalar, ...] = ()


@dataclass(frozen=True, slots=True)
class ModeRule:
    mode: DownloadMode
    object_param: str | None = None
    point_param: str | None = None
    range_start_param: str | None = None
    range_end_param: str | None = None
    allowed_filters: tuple[str, ...] = ()
    enum_dimensions: tuple[EnumRule, ...] = ()
    unit_enum_dimensions: tuple[str, ...] = ()
    allow_empty_objects: bool = False
    allow_empty_points: bool = False
    allow_empty_object_ranges: bool = False


@dataclass(frozen=True, slots=True)
class PaginationRule:
    strategy: int = 1
    effective_limit: int | None = None
    offset_start: int | None = None
    offset_step: int | None = None
    limit_param: str | None = None
    offset_param: str | None = None
    short_page_ends: bool = True
    empty_page_ends: bool = True
    reliable_total_path: tuple[str, ...] | None = None
    reliable_next_offset_path: tuple[str, ...] | None = None
    truncation_limit: int | None = None
    split_time_rule_key: str | None = None


_FORMATS = {
    "YYYY-MM-DD": "%Y-%m-%d",
    "YYYYMMDD": "%Y%m%d",
    "YYYY-MM": "%Y-%m",
    "YYYYMM": "%Y%m",
    "YYYY-MM-DD HH:MM:SS": "%Y-%m-%d %H:%M:%S",
    "YYYYMMDD HH:MM:SS": "%Y%m%d %H:%M:%S",
}


@dataclass(frozen=True, slots=True)
class TimeRule:
    rule_key: str
    rule_version: str
    input_format: str
    source_format: str
    source_time_field: str
    range_bounds: str = "closed"
    minimum_step: int = 1
    timezone: str | None = None

    def parse(self, value: str, *, source: bool = False) -> datetime:
        fmt = _FORMATS[self.source_format if source else self.input_format]
        if type(value) is not str:
            raise ValueError("time text is required")
        parsed = datetime.strptime(value, fmt)  # noqa: DTZ007 - day/month labels are not instants; timestamps get the declared zone below.
        if parsed.strftime(fmt) != value:
            raise ValueError("time text must use the declared format")
        if self.timezone:
            parsed = parsed.replace(tzinfo=ZoneInfo(self.timezone))
        return parsed

    def to_source(self, value: str) -> str:
        return self.parse(value).strftime(_FORMATS[self.source_format])

    def validate_range(self, value: TimeRange) -> None:
        require(isinstance(value, TimeRange), DownloadErrorCode.INPUT)
        valid = False
        try:
            valid = self.parse(value.start) <= self.parse(value.end)
        except (ValueError, TypeError):
            pass
        require(valid, DownloadErrorCode.INPUT)

    def split(self, value: TimeRange) -> tuple[TimeRange, TimeRange] | None:
        start, end = self.parse(value.start), self.parse(value.end)
        if self.rule_key == "month":
            distance = (end.year - start.year) * 12 + end.month - start.month
            if distance < self.minimum_step:
                return None
            n = start.year * 12 + start.month - 1 + distance // 2
            mid = start.replace(year=n // 12, month=n % 12 + 1)
            n += 1
            right = mid.replace(year=n // 12, month=n % 12 + 1)
        else:
            step = (
                timedelta(days=self.minimum_step)
                if self.rule_key == "day"
                else timedelta(seconds=self.minimum_step)
            )
            distance = (end - start) // step
            if distance < 1:
                return None
            mid = start + step * (distance // 2)
            right = mid + step
        fmt = _FORMATS[self.input_format]
        return TimeRange(value.start, mid.strftime(fmt)), TimeRange(
            right.strftime(fmt), value.end
        )


@dataclass(frozen=True, slots=True)
class OrderingRule:
    time_field: str | None = None
    time_rule_key: str | None = None
    rule_version: str = "1"


@dataclass(frozen=True, slots=True)
class SourceDatasetContract:
    contract_name: str
    dataset_id: str
    version: str
    source_api_name: str
    fields: tuple[SourceField, ...]
    parameters: tuple[ParameterRule, ...]
    modes: tuple[ModeRule, ...]
    pagination: PaginationRule
    time_rules: tuple[TimeRule, ...] = ()
    ordering: OrderingRule = OrderingRule()
    source_evidence: tuple[str, ...] = ()
    local_evidence_paths: tuple[str, ...] = ()

    @property
    def field_names(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.fields)

    def mode_rule(self, mode: DownloadMode) -> ModeRule:
        result = next((x for x in self.modes if x.mode == mode), None)
        require(result is not None)
        return result

    def time_rule(self, key: str | None = None) -> TimeRule:
        if key is None:
            key = self.pagination.split_time_rule_key or self.ordering.time_rule_key
        candidates = tuple(
            x for x in self.time_rules if key is None or x.rule_key == key
        )
        require(len(candidates) == 1)
        return candidates[0]
