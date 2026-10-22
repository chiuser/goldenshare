"""One assembled registry supplies both calculation execution and discovery."""

from __future__ import annotations

from collections.abc import Callable
from types import MappingProxyType
from typing import TYPE_CHECKING

from ..contracts import Parameters
from ..errors import CalculationUnsupportedError, RequestInvalidError
from .calculation import Calculation, CalculationDefinition

if TYPE_CHECKING:
    from ..contracts import CalculationRequest
    from .dependencies import CalculationPlan


class CalculationRegistry:
    """Register actual factories during assembly, then freeze before use."""

    def __init__(self) -> None:
        self._definitions: dict[str, CalculationDefinition] = {}
        self._factories: dict[str, Callable[[Parameters], Calculation]] = {}
        self._frozen = False

    def register(
        self,
        definition: CalculationDefinition,
        factory: Callable[[Parameters], Calculation],
    ) -> None:
        if self._frozen:
            raise RequestInvalidError("Calculation registry is already frozen")
        if not isinstance(definition, CalculationDefinition) or not callable(factory):
            raise RequestInvalidError("Registration requires a definition and a callable calculation factory")
        if definition.calculation_id in self._definitions:
            raise RequestInvalidError("A calculation ID may only have one registered definition and version")
        self._definitions[definition.calculation_id] = definition
        self._factories[definition.calculation_id] = factory

    def freeze(self) -> None:
        """Stop registration; repeated freezing is harmless."""
        if not self._frozen:
            self._definitions = MappingProxyType(self._definitions)
            self._factories = MappingProxyType(self._factories)
            self._frozen = True

    def resolve(self, calculation_id: str) -> CalculationDefinition:
        definition = self._definition(calculation_id)
        if not definition.public:
            raise CalculationUnsupportedError("Internal calculations cannot be requested directly")
        return definition

    def resolve_dependency(self, calculation_id: str, algorithm_version: str) -> CalculationDefinition:
        definition = self._definition(calculation_id)
        if definition.algorithm_version != algorithm_version:
            raise CalculationUnsupportedError("The requested dependency version is not registered")
        return definition

    def public_definitions(self) -> tuple[CalculationDefinition, ...]:
        return tuple(item for item in self._definitions.values() if item.public)

    def expand_dependencies(self, normalized: CalculationRequest) -> CalculationPlan:
        from .dependencies import expand_dependencies

        if not self._frozen:
            raise RequestInvalidError("Freeze the calculation registry before planning a request")
        return expand_dependencies(self, normalized)

    def _definition(self, calculation_id: str) -> CalculationDefinition:
        try:
            return self._definitions[calculation_id]
        except (KeyError, TypeError) as exc:
            raise CalculationUnsupportedError("Calculation is not registered") from exc

    def _create(self, definition: CalculationDefinition, parameters: Parameters) -> Calculation:
        calculation = self._factories[definition.calculation_id](parameters)
        required = ("input_requirement", "dependencies", "prepare", "consume", "release_batch", "release")
        if not all(callable(getattr(calculation, name, None)) for name in required):
            raise RequestInvalidError("Calculation factory must return the complete Calculation contract")
        return calculation
