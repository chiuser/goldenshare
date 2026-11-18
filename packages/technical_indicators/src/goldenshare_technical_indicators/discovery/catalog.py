"""Describe registered calculations and explicitly assembled source support."""

from dataclasses import dataclass

from ..calculation.calculation import CalculationDefinition
from ..calculation.registry import CalculationRegistry
from ..configuration.settings import KernelConfig
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


def _source_capabilities(config: KernelConfig | None) -> tuple[SourceCapability, ...]:
    if config is None:
        return ()
    return tuple(
        SourceCapability(security_type, period, adjustment, dataset_id)
        for (security_type, period), dataset_id in config.market_datasets.items()
        for adjustment in sorted(config.enabled_adjustments(dataset_id))
    )


def list_calculations(
    registry: CalculationRegistry, *, config: KernelConfig | None = None,
) -> tuple[CalculationDescription, ...]:
    """Describe calculations using the selected backend's enabled sources."""
    capabilities = _source_capabilities(config)
    return tuple(_describe(item, capabilities) for item in registry.public_definitions())


def describe_calculation(
    registry: CalculationRegistry,
    calculation_id: str,
    *,
    config: KernelConfig | None = None,
) -> CalculationDescription:
    return _describe(registry.resolve(calculation_id), _source_capabilities(config))
