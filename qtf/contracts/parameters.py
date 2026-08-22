from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType

from qtf.contracts.errors import QtfRequestInvalid


class ParameterKind(StrEnum):
    INTEGER = "INTEGER"
    NUMBER = "NUMBER"
    STRING = "STRING"
    INTEGER_SEQUENCE = "INTEGER_SEQUENCE"
    MAPPING = "MAPPING"


class ParameterValueSource(StrEnum):
    FIXED = "FIXED"
    CANDIDATE = "CANDIDATE"


@dataclass(frozen=True, slots=True)
class ParameterDefinition:
    key: str
    kind: ParameterKind
    candidate_dimension: bool
    allowed_values: tuple[object, ...] = ()
    minimum: int | float | Decimal | None = None
    maximum: int | float | Decimal | None = None
    minimum_inclusive: bool = True
    maximum_inclusive: bool = True
    has_default: bool = False
    default_value: object | None = None


@dataclass(frozen=True, slots=True)
class ParameterSchema:
    schema_key: str
    schema_version: str
    fields: tuple[ParameterDefinition, ...]
    active: bool = True

    @property
    def identity(self) -> tuple[str, str]:
        return self.schema_key, self.schema_version


@dataclass(frozen=True, slots=True)
class EffectiveParameterSet:
    schema_key: str
    schema_version: str
    values: Mapping[str, object]
    sources: Mapping[str, ParameterValueSource]
    parameter_hash: str


class ParameterSchemaRegistry:
    def __init__(self, schemas: Iterable[ParameterSchema]) -> None:
        by_identity: dict[tuple[str, str], ParameterSchema] = {}
        for schema in schemas:
            identity = schema.identity
            if identity in by_identity:
                raise ValueError(f"duplicate parameter schema registration: {identity[0]}@{identity[1]}")
            field_keys = [field.key for field in schema.fields]
            if len(field_keys) != len(set(field_keys)):
                raise ValueError(f"duplicate parameter field in schema: {identity[0]}@{identity[1]}")
            by_identity[identity] = schema
        self._by_identity = MappingProxyType(by_identity)

    def get(self, schema_key: str, schema_version: str) -> ParameterSchema:
        identity = (schema_key, schema_version)
        schema = self._by_identity.get(identity)
        if schema is None or not schema.active:
            raise QtfRequestInvalid(f"parameter schema is not registered: {schema_key}@{schema_version}")
        return schema
