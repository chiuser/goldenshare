from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from types import MappingProxyType

from qtf.contracts.errors import QtfRequestInvalid
from qtf.contracts.parameters import (
    EffectiveParameterSet,
    ParameterDefinition,
    ParameterKind,
    ParameterSchema,
    ParameterValueSource,
)
from qtf.engine.canonical_hash import canonical_json_hash


DependencyValidator = Callable[[Mapping[str, object]], None]


def resolve_effective_parameters(
    schema: ParameterSchema,
    values: Mapping[str, object],
    sources: Mapping[str, ParameterValueSource | str],
    *,
    dependency_validator: DependencyValidator | None = None,
) -> EffectiveParameterSet:
    definitions = {field.key: field for field in schema.fields}
    _require_exact_keys("parameter values", values, definitions)
    _require_exact_keys("parameter sources", sources, definitions)

    normalized_values = {
        key: _normalize_value(definitions[key], values[key])
        for key in sorted(definitions)
    }
    normalized_sources: dict[str, ParameterValueSource] = {}
    for key in sorted(definitions):
        try:
            source = ParameterValueSource(sources[key])
        except (TypeError, ValueError) as exc:
            raise QtfRequestInvalid(f"invalid parameter source for {key}") from exc
        if source is ParameterValueSource.CANDIDATE and not definitions[key].candidate_dimension:
            raise QtfRequestInvalid(f"parameter is not an approved candidate dimension: {key}")
        normalized_sources[key] = source

    if dependency_validator is not None:
        dependency_validator(normalized_values)

    hash_payload = {
        "schema_key": schema.schema_key,
        "schema_version": schema.schema_version,
        "values": normalized_values,
        "sources": normalized_sources,
    }
    return EffectiveParameterSet(
        schema_key=schema.schema_key,
        schema_version=schema.schema_version,
        values=MappingProxyType(normalized_values),
        sources=MappingProxyType(normalized_sources),
        parameter_hash=canonical_json_hash(hash_payload),
    )


def _require_exact_keys(
    label: str,
    actual: Mapping[str, object],
    expected: Mapping[str, ParameterDefinition],
) -> None:
    missing = sorted(set(expected) - set(actual))
    unknown = sorted(set(actual) - set(expected))
    if missing or unknown:
        raise QtfRequestInvalid(f"{label} do not match schema; missing={missing}, unknown={unknown}")


def _normalize_value(definition: ParameterDefinition, value: object) -> object:
    if definition.kind is ParameterKind.INTEGER:
        if isinstance(value, bool) or not isinstance(value, int):
            raise QtfRequestInvalid(f"parameter must be an integer: {definition.key}")
        normalized: object = value
    elif definition.kind is ParameterKind.NUMBER:
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
            raise QtfRequestInvalid(f"parameter must be numeric: {definition.key}")
        normalized_number = float(value)
        if not math.isfinite(normalized_number):
            raise QtfRequestInvalid(f"parameter must be finite: {definition.key}")
        normalized = normalized_number
    elif definition.kind is ParameterKind.STRING:
        if not isinstance(value, str) or not value.strip():
            raise QtfRequestInvalid(f"parameter must be a non-empty string: {definition.key}")
        normalized = value.strip()
    elif definition.kind is ParameterKind.INTEGER_SEQUENCE:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
            raise QtfRequestInvalid(f"parameter must be an integer sequence: {definition.key}")
        if any(isinstance(item, bool) or not isinstance(item, int) for item in value):
            raise QtfRequestInvalid(f"parameter must contain only integers: {definition.key}")
        normalized = tuple(value)
    elif definition.kind is ParameterKind.MAPPING:
        if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
            raise QtfRequestInvalid(f"parameter must be a string-keyed mapping: {definition.key}")
        normalized = MappingProxyType(dict(value))
    else:
        raise QtfRequestInvalid(f"unsupported parameter kind: {definition.key}")

    if definition.allowed_values and normalized not in definition.allowed_values:
        raise QtfRequestInvalid(f"parameter value is not allowed: {definition.key}")
    if definition.kind in {ParameterKind.INTEGER, ParameterKind.NUMBER}:
        _validate_numeric_bounds(definition, normalized)
    return normalized


def _validate_numeric_bounds(definition: ParameterDefinition, value: object) -> None:
    numeric = float(value)  # type: ignore[arg-type]
    if definition.minimum is not None:
        minimum = float(definition.minimum)
        below = numeric < minimum if definition.minimum_inclusive else numeric <= minimum
        if below:
            raise QtfRequestInvalid(f"parameter is below its minimum: {definition.key}")
    if definition.maximum is not None:
        maximum = float(definition.maximum)
        above = numeric > maximum if definition.maximum_inclusive else numeric >= maximum
        if above:
            raise QtfRequestInvalid(f"parameter is above its maximum: {definition.key}")
