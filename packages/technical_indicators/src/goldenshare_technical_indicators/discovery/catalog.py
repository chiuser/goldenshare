"""Describe registered calculations and explicitly assembled source support."""

from dataclasses import dataclass

from ..calculation.calculation import CalculationDefinition
from ..calculation.registry import CalculationRegistry
from ..contracts import Adjustment, Period, SecurityType


@dataclass(frozen=True, slots=True)
class SourceCapability:
    security_type: SecurityType
    period: Period
    adjustment: Adjustment
    source_id: str


@dataclass(frozen=True, slots=True)
class CalculationDescription:
    definition: CalculationDefinition
    source_capabilities: tuple[SourceCapability, ...]
    source_supported: bool

    def __post_init__(self) -> None:
        capabilities = tuple(self.source_capabilities)
        if not all(isinstance(item, SourceCapability) for item in capabilities):
            raise ValueError("Source declarations require SourceCapability objects")
        object.__setattr__(self, "source_capabilities", capabilities)


def _describe(
    definition: CalculationDefinition, source_capabilities: tuple[SourceCapability, ...],
) -> CalculationDescription:
    supported = tuple(item for item in source_capabilities if item.period in definition.supported_periods)
    return CalculationDescription(definition, supported, bool(supported))


def list_calculations(
    registry: CalculationRegistry, *, source_capabilities: tuple[SourceCapability, ...] = (),
) -> tuple[CalculationDescription, ...]:
    """No source declaration means unsupported; discovery performs no I/O."""
    capabilities = tuple(source_capabilities)
    return tuple(_describe(item, capabilities) for item in registry.public_definitions())


def describe_calculation(
    registry: CalculationRegistry,
    calculation_id: str,
    *,
    source_capabilities: tuple[SourceCapability, ...] = (),
) -> CalculationDescription:
    return _describe(registry.resolve(calculation_id), tuple(source_capabilities))
