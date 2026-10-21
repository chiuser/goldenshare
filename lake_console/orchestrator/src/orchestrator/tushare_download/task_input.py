"""Bounded input freezing; absent collections never become an all-market query."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .contract_registry import canonical_content
from .download_errors import DownloadErrorCode, require
from .download_models import (
    DownloadMode,
    DownloadTask,
    ObjectTimeRange,
    SourceScalar,
    TimeRange,
)
from .source_contract import SourceDatasetContract, scalar_matches, valid_scalar

INPUT = DownloadErrorCode.INPUT


@dataclass(frozen=True, slots=True)
class FrozenTaskInput:
    contract_name: str
    mode: DownloadMode
    objects: tuple[str, ...] | None
    points: tuple[str, ...] | None
    time_range: TimeRange | None
    object_ranges: tuple[ObjectTimeRange, ...] | None
    filters: tuple[tuple[str, SourceScalar], ...]
    enum_values: tuple[tuple[str, tuple[SourceScalar, ...]], ...]


class _InputCapacity:
    def __init__(self, limit):
        self.limit, self.used = limit, 0

    def scalar(self, value):
        require(valid_scalar(value), INPUT)
        if type(value) is str:
            require(len(value) <= self.limit, DownloadErrorCode.CAPACITY)
        self.used += len(canonical_content(value)) + 8
        require(self.used <= self.limit, DownloadErrorCode.CAPACITY)
        return value


def _object(value, capacity):
    value = capacity.scalar(value)
    require(type(value) is str and bool(value) and value == value.strip(), INPUT)
    require(value != "__ALL__" and not any(x in value for x in ("*", ",")), INPUT)
    return value


def _collection(value, converter, allow_empty):
    if value is None:
        return None
    require(type(value) in (tuple, list), INPUT)
    result = tuple(converter(x) for x in value)
    require(bool(result) or allow_empty, INPUT)
    keys = tuple(canonical_content(x) for x in result)
    require(len(set(keys)) == len(keys), INPUT)
    return result


def validate_task(
    task: DownloadTask, contract: SourceDatasetContract, max_bytes: int
) -> FrozenTaskInput:
    require(
        isinstance(task, DownloadTask) and isinstance(task.mode, DownloadMode), INPUT
    )
    require(task.contract_name == contract.contract_name, INPUT)
    mode = contract.mode_rule(task.mode)
    capacity = _InputCapacity(max_bytes)
    capacity.scalar(task.contract_name)

    def point(value):
        capacity.scalar(value)
        valid = False
        try:
            contract.time_rule().parse(value)
            valid = True
        except (ValueError, TypeError):
            pass
        require(valid, INPUT)
        return value

    def time_range(value):
        require(isinstance(value, TimeRange), INPUT)
        capacity.scalar(value.start)
        capacity.scalar(value.end)
        contract.time_rule().validate_range(value)
        return TimeRange(value.start, value.end)

    def object_range(value):
        require(isinstance(value, ObjectTimeRange), INPUT)
        return ObjectTimeRange(
            _object(value.object_code, capacity), time_range(value.time_range)
        )

    objects = _collection(
        task.objects, lambda x: _object(x, capacity), mode.allow_empty_objects
    )
    points = _collection(task.points, point, mode.allow_empty_points)
    ranges = _collection(
        task.object_ranges, object_range, mode.allow_empty_object_ranges
    )
    common = time_range(task.time_range) if task.time_range is not None else None
    if ranges is not None:
        require(len({x.object_code for x in ranges}) == len(ranges), INPUT)
    if task.mode == DownloadMode.SNAPSHOT:
        require(all(x is None for x in (objects, points, common, ranges)), INPUT)
    elif task.mode == DownloadMode.BY_POINT:
        require(points is not None and objects is None and ranges is None, INPUT)
    elif task.mode == DownloadMode.BY_OBJECT:
        require(
            objects is not None and all(x is None for x in (points, common, ranges)),
            INPUT,
        )
    elif task.mode == DownloadMode.BY_OBJECT_POINT:
        require(objects is not None and points is not None and ranges is None, INPUT)
    elif task.mode == DownloadMode.BY_OBJECT_RANGE:
        require(points is None, INPUT)
        require(
            (ranges is not None and objects is None and common is None)
            or (ranges is None and objects is not None and common is not None),
            INPUT,
        )
    else:
        require(
            common is not None and all(x is None for x in (objects, points, ranges)),
            INPUT,
        )
    if points is not None:
        rule = contract.time_rule()
        if common is not None:
            require(
                all(
                    rule.parse(common.start) <= rule.parse(x) <= rule.parse(common.end)
                    for x in points
                ),
                INPUT,
            )
        points = tuple(sorted(points, key=rule.parse))
    params = {p.name: p for p in contract.parameters}
    filters = task.filters if task.filters is not None else {}
    require(isinstance(filters, Mapping), INPUT)
    frozen_filters = []
    for name, value in filters.items():
        require(name in mode.allowed_filters, INPUT)
        capacity.scalar(name)
        capacity.scalar(value)
        p = params[name]
        require(scalar_matches(value, p.source_kind, p.nullable), INPUT)
        require(
            p.choices is None
            or canonical_content(value) in {canonical_content(x) for x in p.choices},
            INPUT,
        )
        frozen_filters.append((name, value))
    enums = task.enum_values if task.enum_values is not None else {}
    require(isinstance(enums, Mapping), INPUT)
    require(set(enums) <= {e.parameter_name for e in mode.enum_dimensions}, INPUT)
    selected = []
    for e in mode.enum_dimensions:
        values = enums.get(
            e.parameter_name, e.default_values if e.has_default else None
        )
        require(type(values) in (tuple, list) and bool(values), INPUT)
        keys = tuple(canonical_content(capacity.scalar(v)) for v in values)
        require(len(set(keys)) == len(keys), INPUT)
        allowed = tuple(canonical_content(x) for x in e.ordered_values)
        require(set(keys) <= set(allowed), INPUT)
        selected.append(
            (
                e.parameter_name,
                tuple(v for v, key in zip(e.ordered_values, allowed) if key in keys),
            )
        )
    return FrozenTaskInput(
        task.contract_name,
        task.mode,
        objects,
        points,
        common,
        ranges,
        tuple(sorted(frozen_filters)),
        tuple(selected),
    )
