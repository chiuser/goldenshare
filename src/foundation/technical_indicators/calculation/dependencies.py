"""Expand declared dependencies into immutable, request-local nodes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from ..contracts import CalculationRequest, Parameters, _freeze_parameters
from ..errors import CalculationUnsupportedError, RequestInvalidError
from .calculation import Calculation, CalculationDefinition, Dependency

if TYPE_CHECKING:
    from .registry import CalculationRegistry


@dataclass(frozen=True, slots=True)
class CalculationNode:
    node_index: int
    definition: CalculationDefinition
    parameters: Parameters
    calculation: Calculation
    dependencies: Mapping[str, int]

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", _freeze_parameters(self.parameters))
        object.__setattr__(self, "dependencies", MappingProxyType(dict(self.dependencies)))


@dataclass(frozen=True, slots=True)
class CalculationPlan:
    nodes: tuple[CalculationNode, ...]
    instances: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "nodes", tuple(self.nodes))
        object.__setattr__(self, "instances", tuple(tuple(item) for item in self.instances))


def expand_dependencies(registry: CalculationRegistry, normalized: CalculationRequest) -> CalculationPlan:
    """Validate every public instance before invoking any calculation factory."""
    if not isinstance(normalized, CalculationRequest):
        raise RequestInvalidError("A CalculationRequest is required")
    validated = []
    for instance in normalized.calculations:
        definition = registry.resolve(instance.calculation_id)
        if normalized.period not in definition.supported_periods:
            raise CalculationUnsupportedError("Calculation does not support the requested period")
        parameters = definition.validate_parameters(instance.parameters)
        validated.append((instance.instance_id, definition, parameters))

    context = (normalized.security_type, normalized.ts_code, normalized.period, normalized.adjustment)
    completed: dict[tuple, int] = {}
    visiting: set[tuple] = set()
    nodes: list[CalculationNode] = []

    def visit(definition: CalculationDefinition, parameters: Parameters) -> int:
        key = (*context, definition.calculation_id, definition.algorithm_version, parameters, definition.initialization)
        if key in visiting:
            raise RequestInvalidError("Calculation dependencies contain a cycle")
        if key in completed:
            return completed[key]
        visiting.add(key)
        calculation = registry._create(definition, parameters)
        declared = calculation.dependencies()
        if not isinstance(declared, tuple) or not all(isinstance(item, Dependency) for item in declared):
            raise RequestInvalidError("Calculation dependencies must be a tuple of Dependency objects")
        dependencies: dict[str, int] = {}
        for dependency in declared:
            if not isinstance(dependency.role, str) or not dependency.role or dependency.role in dependencies:
                raise RequestInvalidError("Each dependency role must be nonempty and unique within its parent")
            upstream = registry.resolve_dependency(dependency.calculation_id, dependency.algorithm_version)
            if normalized.period not in upstream.supported_periods:
                raise CalculationUnsupportedError("Dependency does not support the requested period")
            if not isinstance(dependency.parameters, tuple):
                raise RequestInvalidError("Dependency parameters require immutable name/value pairs")
            try:
                parameter_mapping = dict(dependency.parameters)
            except (TypeError, ValueError) as exc:
                raise RequestInvalidError("Dependency parameters require name/value pairs") from exc
            if len(parameter_mapping) != len(dependency.parameters):
                raise RequestInvalidError("Dependency parameters contain duplicate names")
            upstream_parameters = upstream.validate_parameters(parameter_mapping)
            dependencies[dependency.role] = visit(upstream, upstream_parameters)
        node_index = len(nodes)
        nodes.append(CalculationNode(node_index, definition, parameters, calculation, dependencies))
        visiting.remove(key)
        completed[key] = node_index
        return node_index

    instances = tuple((instance_id, visit(definition, parameters)) for instance_id, definition, parameters in validated)
    return CalculationPlan(tuple(nodes), instances)
