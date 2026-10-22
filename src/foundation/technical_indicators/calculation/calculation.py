"""Calculation definitions and per-request contracts; no numerical execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
import math
from typing import Protocol, Literal, TYPE_CHECKING

from ..contracts import Parameters, ParameterValue, PERIODS, Period, _freeze_parameters
from ..errors import CalculationUnsupportedError, RequestInvalidError
from .history import HistoryRequirement

if TYPE_CHECKING:
    from ..sources.contracts import PriceBatch


@dataclass(frozen=True, slots=True)
class ParameterSpec:
    name: str
    kind: Literal["positive_integer", "finite_nonnegative"]
    default: int | float

    def validate(self, value: ParameterValue) -> int | float:
        if self.kind == "positive_integer":
            if type(value) is not int or value <= 0:
                raise RequestInvalidError(f"{self.name} must be a positive integer")
        elif self.kind == "finite_nonnegative":
            if type(value) not in (int, float):
                raise RequestInvalidError(f"{self.name} must be a finite nonnegative number")
            try:
                valid = math.isfinite(value) and value >= 0
            except OverflowError:
                valid = False
            if not valid:
                raise RequestInvalidError(f"{self.name} must be a finite nonnegative number")
        else:
            raise ValueError("Unknown parameter definition kind")
        return value


@dataclass(frozen=True, slots=True)
class OutputField:
    name: str
    column_name: str
    sql_type: Literal["DOUBLE"]
    nullable: bool
    initialization_rule: str


@dataclass(frozen=True, slots=True)
class CalculationDefinition:
    calculation_id: str
    algorithm_version: str
    description: str
    parameter_specs: tuple[ParameterSpec, ...]
    input_fields: frozenset[str]
    output_fields: tuple[OutputField, ...]
    initialization: str
    history_rule: str
    units: tuple[tuple[str, str], ...]
    supported_periods: tuple[Period, ...] = PERIODS
    public: bool = True
    parameter_relations: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameter_specs", tuple(self.parameter_specs))
        object.__setattr__(self, "input_fields", frozenset(self.input_fields))
        object.__setattr__(self, "output_fields", tuple(self.output_fields))
        object.__setattr__(self, "units", tuple(tuple(item) for item in self.units))
        object.__setattr__(self, "supported_periods", tuple(self.supported_periods))
        object.__setattr__(self, "parameter_relations", tuple(tuple(item) for item in self.parameter_relations))
        names = tuple(spec.name for spec in self.parameter_specs)
        if len(set(names)) != len(names):
            raise ValueError("Duplicate parameter definition")
        for spec in self.parameter_specs:
            spec.validate(spec.default)
        if any(left not in names or right not in names for left, right in self.parameter_relations):
            raise ValueError("Parameter relation references an undefined parameter")

    def validate_parameters(self, mapping: Mapping[str, ParameterValue]) -> Parameters:
        if not isinstance(mapping, Mapping):
            raise RequestInvalidError("parameters must be a mapping")
        known = {spec.name for spec in self.parameter_specs}
        if set(mapping) - known:
            raise CalculationUnsupportedError("Unknown calculation parameter")
        normalized = tuple((spec.name, spec.validate(mapping.get(spec.name, spec.default))) for spec in self.parameter_specs)
        values = dict(normalized)
        if any(values[left] >= values[right] for left, right in self.parameter_relations):
            raise RequestInvalidError("Calculation requires its declared first period to be smaller than the second")
        return normalized


@dataclass(frozen=True, slots=True)
class Dependency:
    role: str
    calculation_id: str
    algorithm_version: str
    parameters: Parameters

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", _freeze_parameters(self.parameters))


@dataclass(frozen=True, slots=True)
class SqlStep:
    name: str
    sql: str
    bindings: tuple[int | float | bool | str | date | datetime | None, ...]
    input_tables: tuple[str, ...]
    output_tables: tuple[str, ...]
    processed_rows: int

    def __post_init__(self) -> None:
        if not isinstance(self.bindings, (tuple, list)):
            raise ValueError("SQL bindings require a scalar sequence")
        bindings = tuple(self.bindings)
        if any(type(value) not in (int, float, bool, str, date, datetime, type(None)) for value in bindings):
            raise ValueError("SQL bindings must be immutable scalar values")
        object.__setattr__(self, "bindings", bindings)
        for name in ("input_tables", "output_tables"):
            values = getattr(self, name)
            if not isinstance(values, (tuple, list)) or not all(isinstance(item, str) for item in values):
                raise ValueError("SQL table names require a string sequence")
            object.__setattr__(self, name, tuple(values))


@dataclass(frozen=True, slots=True)
class ExecutionStats:
    step_name: str
    elapsed_ms: float
    logical_input_rows: int
    output_rows: int
    failed: bool


@dataclass(frozen=True, slots=True)
class CalculationOutput:
    table_name: str
    fields: tuple[OutputField, ...]
    new_first_seq: int
    new_last_seq: int
    sequence_field: str = "seq"

    def __post_init__(self) -> None:
        fields = tuple(self.fields)
        if not all(isinstance(item, OutputField) for item in fields):
            raise ValueError("Calculation output fields require OutputField objects")
        object.__setattr__(self, "fields", fields)


@dataclass(slots=True)
class CalculationSession:
    """Mutable state belongs to one node in one request, never a registry."""

    executor: object
    node_index: int
    parameters: Parameters
    dependencies: Mapping[str, CalculationOutput]
    state_tables: list[str]
    batch_tables: list[str]
    initialized: bool = False


@dataclass(frozen=True, slots=True)
class BatchCalculationOutputs:
    price_batch: PriceBatch
    instances: tuple[tuple[str, CalculationOutput], ...]

    def __post_init__(self) -> None:
        copied = []
        for item in self.instances:
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                raise ValueError("Batch output instances require identity/output pairs")
            identity, output = item
            if not isinstance(identity, str) or not isinstance(output, CalculationOutput):
                raise ValueError("Batch output instances require identity/output pairs")
            copied.append((identity, output))
        object.__setattr__(self, "instances", tuple(copied))


class Calculation(Protocol):
    def input_requirement(self) -> HistoryRequirement: ...
    def dependencies(self) -> tuple[Dependency, ...]: ...
    def prepare(self, session: CalculationSession) -> None: ...
    def consume(self, batch: PriceBatch, session: CalculationSession) -> CalculationOutput: ...
    def release_batch(self, session: CalculationSession) -> None: ...
    def release(self, session: CalculationSession) -> None: ...
