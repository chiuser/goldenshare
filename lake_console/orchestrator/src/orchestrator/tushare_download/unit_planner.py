"""Lazy six-mode unit planning; identifiers describe intent, never persistence."""

from __future__ import annotations

from itertools import product
from math import prod

from .contract_registry import content_digest
from .download_models import DownloadMode, DownloadUnit


class UnitPlanner:
    def __init__(self, task, contract):
        self.task, self.contract = task, contract
        mode = contract.mode_rule(task.mode)
        enums = dict(task.enum_values)
        groups = prod(len(enums[key]) for key in mode.unit_enum_dimensions)
        basic = {
            DownloadMode.SNAPSHOT: 1,
            DownloadMode.BY_POINT: len(task.points or ()),
            DownloadMode.BY_OBJECT: len(task.objects or ()),
            DownloadMode.BY_OBJECT_POINT: len(task.objects or ())
            * len(task.points or ()),
            DownloadMode.BY_OBJECT_RANGE: len(
                task.object_ranges
                if task.object_ranges is not None
                else task.objects or ()
            ),
            DownloadMode.BY_RANGE: 1,
        }[task.mode]
        self.total_units = basic * groups
        self._digest = content_digest(contract)
        self._units = self._expand(mode, enums)

    def _base(self):
        task = self.task
        if task.mode == DownloadMode.SNAPSHOT:
            yield None, None, None
        elif task.mode == DownloadMode.BY_POINT:
            for point in task.points:
                yield None, point, None
        elif task.mode == DownloadMode.BY_OBJECT:
            for code in task.objects:
                yield code, None, None
        elif task.mode == DownloadMode.BY_OBJECT_POINT:
            for point in task.points:
                for code in task.objects:
                    yield code, point, None
        elif task.mode == DownloadMode.BY_OBJECT_RANGE:
            if task.object_ranges is not None:
                for value in task.object_ranges:
                    yield value.object_code, None, value.time_range
            else:
                for code in task.objects:
                    yield code, None, task.time_range
        else:
            yield None, None, task.time_range

    def _expand(self, mode, enums):
        independent = tuple(
            key for key, _ in self.task.enum_values if key in mode.unit_enum_dimensions
        )
        ordinal = 0
        for code, point, time_range in self._base():
            for selection in product(*(enums[key] for key in independent)):
                chosen = dict(zip(independent, selection, strict=True))
                values = tuple(
                    (key, (chosen[key],) if key in chosen else value)
                    for key, value in self.task.enum_values
                )
                identity = (
                    self.contract.contract_name,
                    self.contract.version,
                    self._digest,
                    self.task.mode,
                    code,
                    point,
                    time_range,
                    self.task.filters,
                    values,
                )
                ordinal += 1
                yield DownloadUnit(
                    ordinal,
                    content_digest(identity),
                    self.contract.contract_name,
                    self.contract.version,
                    self._digest,
                    self.task.mode,
                    code,
                    point,
                    time_range,
                    self.task.filters,
                    values,
                )

    def next_unit(self):
        return next(self._units, None)

    def close(self):
        self._units.close()
        self.task = self.contract = None
