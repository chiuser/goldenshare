"""Return the target prices already prepared by the input session."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import ClassVar

from ...contracts import Parameters, _freeze_parameters
from ..calculation import CalculationDefinition, CalculationOutput, OutputField
from ..history import HistoryRequirement

_FIELDS = ("open", "high", "low", "close", "volume", "amount")
DEFINITION = CalculationDefinition(
    calculation_id="price", algorithm_version="1.0.0",
    description="目标复权口径的OHLC、成交量和成交额",
    parameter_specs=(), input_fields=frozenset(_FIELDS),
    output_fields=tuple(OutputField(name, name, "DOUBLE", False, "目标价格原样") for name in _FIELDS),
    initialization="不重新初始化或改写价格/量额", history_rule="无前置历史",
    units=tuple((name, "source_" + ("price" if name in _FIELDS[:4] else name) + "_unit") for name in _FIELDS),
)


@dataclass(frozen=True, slots=True)
class PriceCalculation:
    parameters: Parameters

    TABLE_ROLES: ClassVar = MappingProxyType({})
    SQL_FILES: ClassVar = ()
    FIXED_SQL_STEPS: ClassVar = MappingProxyType({})
    SQL_PACKAGE: ClassVar = "src.foundation.technical_indicators.calculation"

    def __post_init__(self):
        object.__setattr__(self, "parameters", _freeze_parameters(self.parameters))

    def input_requirement(self):
        return HistoryRequirement(DEFINITION.input_fields, 0, False, (), DEFINITION.initialization)

    def dependencies(self):
        return ()

    def prepare(self, session):
        pass

    def consume(self, batch, session):
        return CalculationOutput(batch.table_name, DEFINITION.output_fields,
                                 batch.new_first_seq, batch.new_last_seq)

    def release_batch(self, session):
        pass

    def release(self, session):
        pass
