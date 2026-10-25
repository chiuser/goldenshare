"""Count or produce strict JSON without retaining a second serialized result."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields
from datetime import date, datetime
from enum import Enum
from io import BytesIO
import json

from ..contracts import (
    CalculationResult, CalculationStatistics, CalculationValues, OutputRange,
    PriceAdjustmentResult, RequestedRange, SeriesDescription, SourceResult,
)
from ..errors import OutputEncodingError, ResourceLimitError
from ..execution_control import ExecutionControl


_RESULT_TYPES = (
    CalculationResult, CalculationStatistics, OutputRange,
    PriceAdjustmentResult, RequestedRange, SeriesDescription, SourceResult,
)


class _ContractJSONEncoder(json.JSONEncoder):
    def default(self, value):
        if isinstance(value, CalculationValues):
            # These two tuples express named JSON objects, not pair arrays.
            return {
                "instance_id": value.instance_id,
                "calculation_id": value.calculation_id,
                "algorithm_version": value.algorithm_version,
                "parameters": dict(value.parameters),
                "fields": dict(value.fields),
            }
        if isinstance(value, _RESULT_TYPES):
            # A shallow view keeps large numerical tuples shared with result.
            return {item.name: getattr(value, item.name) for item in fields(value)}
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, Enum) and type(value.value) in (str, int, float, bool, type(None)):
            return value.value
        if isinstance(value, Mapping):
            return dict(value)
        return super().default(value)


def _iter_utf8(payload, *, control: ExecutionControl, max_bytes: int):
    if type(max_bytes) is not int or max_bytes < 0:
        raise OutputEncodingError("The UTF-8 output limit must be a nonnegative integer")
    encoder = _ContractJSONEncoder(allow_nan=False, ensure_ascii=False, separators=(",", ":"))
    total = 0
    try:
        chunks = iter(encoder.iterencode(payload))
        while True:
            control.check_active()
            try:
                chunk = next(chunks)
            except StopIteration:
                break
            encoded = chunk.encode("utf-8")
            total += len(encoded)
            control.check_active()
            if total > max_bytes:
                raise ResourceLimitError("The complete UTF-8 output exceeds max_output_bytes")
            yield encoded
        control.check_active()
    except (TypeError, ValueError, OverflowError, UnicodeError) as exc:
        # Stops and resource-limit errors keep their original kernel classes.
        control.check_active()
        raise OutputEncodingError("The complete result cannot be encoded as strict JSON") from exc


def measure_result_utf8(
    result: CalculationResult, *, control: ExecutionControl, max_bytes: int,
) -> int:
    """Discard each encoded chunk after counting its real UTF-8 bytes."""
    if not isinstance(result, CalculationResult):
        raise OutputEncodingError("Library output measurement requires CalculationResult")
    total = 0
    for chunk in _iter_utf8(result, control=control, max_bytes=max_bytes):
        total += len(chunk)
    return total


def encode_response_utf8(
    payload, *, control: ExecutionControl, max_bytes: int,
) -> bytes:
    """Internal future-adapter helper; build one response body, never partial JSON."""
    with BytesIO() as body:
        for chunk in _iter_utf8(payload, control=control, max_bytes=max_bytes):
            body.write(chunk)
        control.check_active()
        return body.getvalue()
