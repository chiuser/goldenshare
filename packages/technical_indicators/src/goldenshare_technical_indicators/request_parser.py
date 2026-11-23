"""Resolve an instruction without reading market data or opening a calculation session."""

from dataclasses import dataclass

from .calculation.dependencies import CalculationPlan
from .calculation.history import HistoryRequirement, INITIALIZATION_ERROR_BUDGET
from .calculation.registry import CalculationRegistry
from .configuration.settings import KernelConfig
from .contracts import CalculationRequest, normalize_request_and_validate_all_instances
from .errors import SourceUnsupportedError
from .sources.contracts import DatasetReadTarget, ReadRequirement


@dataclass(frozen=True, slots=True)
class _PreparedCalculation:
    request: CalculationRequest
    plan: CalculationPlan
    target: DatasetReadTarget
    max_output_rows: int | None = None
    warmup_error_budget: float = INITIALIZATION_ERROR_BUDGET


class CalculationRequestParser:
    def __init__(self, config: KernelConfig, registry: CalculationRegistry) -> None:
        self._config = config
        self._registry = registry

    def parse(self, request: CalculationRequest) -> _PreparedCalculation:
        normalized = normalize_request_and_validate_all_instances(request, self._config)
        plan = self._registry.expand_dependencies(normalized)
        dataset_id = self._config.market_dataset_id(normalized.security_type, normalized.period)
        if normalized.adjustment not in self._config.enabled_adjustments(dataset_id):
            raise SourceUnsupportedError("Dataset adjustment is not enabled in this environment")
        target = self._config.resolve_dataset_location(dataset_id)
        return _PreparedCalculation(normalized, plan, target)


def _build_read_requirement(
    prepared: _PreparedCalculation, history: HistoryRequirement, *, batch_rows: int,
) -> ReadRequirement:
    """Convert normalized bounds to the source period's time representation."""
    request = prepared.request
    minute = request.period.endswith("m")
    return ReadRequirement(
        target=prepared.target,
        ts_code=request.ts_code,
        period=request.period,
        start=request.start if minute else request.start.date(),
        end=request.end if minute else request.end.date(),
        history=history,
        batch_rows=batch_rows,
        target_adjustment=request.adjustment,
        max_output_rows=prepared.max_output_rows,
    )
