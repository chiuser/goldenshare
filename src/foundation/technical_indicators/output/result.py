"""Assemble detached contracts from the already fetched output rows."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from ..contracts import (
    KERNEL_VERSION, TIMEZONE, CalculationRequest, CalculationResult,
    CalculationStatistics, CalculationValues, OutputRange, PriceAdjustmentResult,
    RequestedRange, SeriesDescription, SourceResult, TimePosition,
)
from ..errors import OutputContractError
from .contracts import OutputInstanceDescription

if TYPE_CHECKING:
    from ..sources.contracts import SourceDescription


def normalize_time(
    value: object, *, minute: bool, stage: str, field_name: str,
) -> TimePosition:
    """Interpret naive minute timestamps only as Shanghai wall-clock times."""
    if minute and isinstance(value, datetime):
        zone = ZoneInfo(TIMEZONE)
        return (value.replace(tzinfo=zone) if value.tzinfo is None or value.utcoffset() is None
                else value.astimezone(zone))
    if not minute and type(value) is date:
        return value
    raise OutputContractError(
        "An output date or time does not match the requested period",
        reason="type_mismatch", stage=stage, field_name=field_name,
        actual_type=type(value).__name__,
    )


def normalize_read_range(
    *, request: CalculationRequest, statistics: CalculationStatistics,
    read_start: TimePosition | None, read_end: TimePosition | None,
) -> tuple[TimePosition | None, TimePosition | None]:
    diagnostics = {"source_rows": statistics.source_rows,
                   "read_start": read_start, "read_end": read_end}
    if (read_start is None) != (read_end is None):
        raise OutputContractError(
            "The actual read start and end must both be present or both absent",
            reason="wrong_batch", stage="final_query", **diagnostics,
        )
    if read_start is None:
        if statistics.source_rows != 0:
            raise OutputContractError(
                "A nonempty source requires its actual read range",
                reason="wrong_batch", stage="final_query", **diagnostics,
            )
        return None, None
    minute = request.period.endswith("m")
    first = normalize_time(read_start, minute=minute, stage="final_query", field_name="read_start")
    last = normalize_time(read_end, minute=minute, stage="final_query", field_name="read_end")
    if first > last or statistics.source_rows <= 0:
        raise OutputContractError(
            "The actual read range does not match the completed source read",
            reason="wrong_batch", stage="final_query", **diagnostics,
        )
    return first, last


def build_calculation_result(
    *, request: CalculationRequest, instances: tuple[OutputInstanceDescription, ...],
    description: SourceDescription, statistics: CalculationStatistics,
    rows: tuple[tuple[object, ...], ...], columns: tuple[str, ...],
    value_columns: tuple[tuple[str, ...], ...],
    read_start: TimePosition | None, read_end: TimePosition | None,
) -> CalculationResult:
    first_read, last_read = normalize_read_range(
        request=request, statistics=statistics, read_start=read_start, read_end=read_end,
    )
    positions = {name: index for index, name in enumerate(columns)}
    minute = request.period.endswith("m")
    time_name = "trade_time" if minute else "period_start"
    times = tuple(normalize_time(row[positions[time_name]], minute=minute,
                                 stage="final_fetch", field_name=time_name) for row in rows)
    source_as_of = None
    if request.period in ("week", "month"):
        source_as_of = tuple(normalize_time(row[positions["source_as_of"]], minute=False,
                                           stage="final_fetch", field_name="source_as_of") for row in rows)
    calculations = tuple(
        CalculationValues(
            item.instance_id, item.calculation_id, item.algorithm_version, item.parameters,
            tuple((field.name, tuple(row[positions[column]] for row in rows))
                  for field, column in zip(item.fields, aliases)),
        )
        for item, aliases in zip(instances, value_columns)
    )
    # Each alias was verified against the SQL contract before reading. Do not
    # scan numerical values or replace legitimate formula/source NULLs.
    if len(calculations) != len(instances) or any(
        len(values.fields) != len(item.fields)
        or any(len(column) != len(times) for _, column in values.fields)
        for item, values in zip(instances, calculations)
    ):
        raise OutputContractError(
            "The detached output does not contain every requested field",
            reason="missing_fields", stage="final_fetch",
        )
    return CalculationResult(
        kernel_version=KERNEL_VERSION,
        series=SeriesDescription(
            request.security_type, request.ts_code, request.period, request.adjustment,
            description.timezone, description.price_unit, description.volume_unit, description.amount_unit,
        ),
        requested=RequestedRange(request.start, request.end, request.before, request.limit),
        source=SourceResult(
            description.source_id, description.contract_version, description.input_adjustment,
            None, first_read, last_read, description.available_through,
        ),
        price_adjustment=PriceAdjustmentResult(
            description.basis_rule,
            {"none": None, "qfq": "latest_factor", "hfq": "earliest_factor"}[request.adjustment],
            description.basis_date, description.basis_value, description.converted, "1.0.0",
        ),
        times=times, source_as_of=source_as_of, calculations=calculations,
        range=OutputRange(times[0] if times else None, times[-1] if times else None, len(times)),
        statistics=statistics,
        msg="已经加载全部数据了" if not times and request.before is not None else "",
    )
