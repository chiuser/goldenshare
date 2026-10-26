"""Calculation definitions and per-request contracts; no numerical execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
import math
from types import MappingProxyType
from typing import Protocol, Literal, TYPE_CHECKING

from ..contracts import Parameters, ParameterValue, PERIODS, Period, _freeze_parameters
from ..errors import CalculationExecutionError, CalculationUnsupportedError, RequestInvalidError
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


@dataclass(frozen=True, slots=True)
class ControlReadStep:
    """A fixed calculation control SELECT; numerical state never leaves SQL."""

    sql: str
    input_roles: tuple[str, ...]
    binding_types: tuple[type, ...]
    expected_columns: tuple[tuple[str, str], ...]
    processed_rows: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "input_roles", tuple(self.input_roles))
        object.__setattr__(self, "binding_types", tuple(self.binding_types))
        object.__setattr__(self, "expected_columns", tuple(tuple(item) for item in self.expected_columns))


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
    readable_tables: frozenset[str] = frozenset()
    allowed_step_names: frozenset[str] = frozenset()
    owned_table_names: frozenset[str] = frozenset()
    current_batch: PriceBatch | None = None
    table_roles: Mapping[str, tuple[str, str]] = field(default_factory=lambda: MappingProxyType({}))
    control_read_steps: Mapping[str, ControlReadStep] = field(default_factory=lambda: MappingProxyType({}))
    sql_templates: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    _cleanup_mode: bool = False

    def __post_init__(self) -> None:
        self.parameters = _freeze_parameters(self.parameters)
        self.dependencies = MappingProxyType(dict(self.dependencies))
        self.readable_tables = frozenset(self.readable_tables)
        self.allowed_step_names = frozenset(self.allowed_step_names)
        self.owned_table_names = frozenset(self.owned_table_names)
        self.table_roles = MappingProxyType({key: tuple(value) for key, value in self.table_roles.items()})
        self.control_read_steps = MappingProxyType(dict(self.control_read_steps))
        self.sql_templates = MappingProxyType(dict(self.sql_templates))

    def _registered_owned(self, name: str) -> bool:
        return name in self.owned_table_names and (name in self.state_tables or name in self.batch_tables)

    def declare_owned_table(self, role: str) -> str:
        """Register this node's fixed name before creating its SQL table."""
        try:
            name, lifetime = self.table_roles[role]
        except KeyError as exc:
            raise CalculationExecutionError("Calculation attempted an undeclared table role") from exc
        if name not in self.owned_table_names:
            raise CalculationExecutionError("Calculation table role does not belong to this node")
        if lifetime == "batch" and self.current_batch is None:
            raise CalculationExecutionError("Batch tables require a current price batch")
        owned = self.state_tables if lifetime == "state" else self.batch_tables
        if name not in owned:
            owned.append(name)
        self.executor.declare_table(name)
        return name

    def _check_tables(self, step: SqlStep) -> None:
        for name in step.input_tables:
            if name not in self.readable_tables and not self._registered_owned(name):
                raise CalculationExecutionError("Calculation attempted to read an undeclared table")
        if any(not self._registered_owned(name) for name in step.output_tables):
            raise CalculationExecutionError("Calculation attempted to write a borrowed or undeclared table")

    def execute(self, step: SqlStep) -> ExecutionStats:
        self.executor.control.check_active()
        if not isinstance(step, SqlStep) or step.name not in self.allowed_step_names:
            raise CalculationExecutionError("Calculation attempted an undeclared SQL step")
        if step.name in self.control_read_steps:
            raise CalculationExecutionError("A control SELECT must use read_control_row")
        self._check_tables(step)
        return self.executor.execute(step)

    def drop_owned_table(self, name: str, *, cleanup: bool = False) -> None:
        if not self._registered_owned(name):
            raise CalculationExecutionError("Calculation cannot delete a borrowed or undeclared table")
        if cleanup and not self._cleanup_mode:
            raise CalculationExecutionError("Calculation cleanup is only available during engine close")
        if cleanup:
            self.executor.cleanup_drop(name)
        else:
            self.executor.drop_table(name)
        for owned in (self.batch_tables, self.state_tables):
            if name in owned:
                owned.remove(name)

    def read_control_row(self, step_name: str, bindings: tuple = ()) -> tuple[int | bool | None, ...]:
        from .sql_templates import render_sql

        self.executor.control.check_active()
        if step_name not in self.allowed_step_names or step_name not in self.control_read_steps:
            raise CalculationExecutionError("Calculation attempted an undeclared control SELECT")
        declared = self.control_read_steps[step_name]
        if not isinstance(bindings, tuple) or len(bindings) != len(declared.binding_types):
            raise CalculationExecutionError("Calculation control bindings do not match the fixed declaration")
        if any(type(value) is not expected for value, expected in zip(bindings, declared.binding_types)):
            raise CalculationExecutionError("Calculation control binding types do not match the fixed declaration")
        if step_name == "read_segment_bounds":
            if self.current_batch is None or bindings != (self.current_batch.new_last_seq,):
                raise CalculationExecutionError("Calculation control endpoint does not match this price batch")
        tables = {role: self.table_roles[role][0] for role in declared.input_roles}
        step = SqlStep(step_name, render_sql(declared.sql, tables=tables), bindings,
                       tuple(tables.values()), (), declared.processed_rows)
        self._check_tables(step)
        row = self.executor.read_control_row(step, expected_columns=declared.expected_columns)
        if step_name == "read_smoothing_limits":
            if row == (None,):
                raise RequestInvalidError("Smoothing parameters cannot be represented by the SQL calculation")
            if len(row) != 1 or type(row[0]) is not int or not 1 <= row[0] <= 1024:
                self._control_error(step_name, "control_bounds")
        elif step_name == "read_segment_bounds":
            if len(row) != 3 or any(type(value) is not int for value in row):
                self._control_error(step_name, "control_types")
            previous, endpoint, size = row
            batch = self.current_batch
            if (not batch.new_first_seq - 1 <= previous <= batch.new_last_seq
                    or not previous <= endpoint <= batch.new_last_seq
                    or size != endpoint - previous or not 0 <= size <= 1024):
                self._control_error(step_name, "control_bounds")
        elif step_name == "read_warmup_rows":
            if len(row) != 2 or type(row[1]) is not bool:
                self._control_error(step_name, "control_types")
            rows, origin = row
            if (origin and rows is not None) or (not origin and (type(rows) is not int or rows < 0)):
                self._control_error(step_name, "control_bounds")
        else:
            raise CalculationExecutionError("The declared SELECT is not a calculation control step")
        return row

    @staticmethod
    def _control_error(step_name: str, reason: str) -> None:
        error = CalculationExecutionError("Calculation control result violates its fixed contract")
        error.step_name, error.reason = step_name, reason
        raise error


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
    def input_requirement(self, session: CalculationSession, max_input_rows: int) -> HistoryRequirement: ...
    def dependencies(self) -> tuple[Dependency, ...]: ...
    def prepare(self, session: CalculationSession) -> None: ...
    def consume(self, batch: PriceBatch, session: CalculationSession) -> CalculationOutput: ...
    def release_batch(self, session: CalculationSession) -> None: ...
    def release(self, session: CalculationSession) -> None: ...
