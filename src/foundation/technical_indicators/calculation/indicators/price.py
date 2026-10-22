"""Price capability definition, shared with its future D3 implementation."""

from ..calculation import CalculationDefinition, OutputField

_FIELDS = ("open", "high", "low", "close", "volume", "amount")
DEFINITION = CalculationDefinition(
    calculation_id="price", algorithm_version="1.0.0",
    description="目标复权口径的OHLC、成交量和成交额",
    parameter_specs=(), input_fields=frozenset(_FIELDS),
    output_fields=tuple(OutputField(name, name, "DOUBLE", False, "目标价格原样") for name in _FIELDS),
    initialization="不重新初始化或改写价格/量额", history_rule="无前置历史",
    units=tuple((name, "source_" + ("price" if name in _FIELDS[:4] else name) + "_unit") for name in _FIELDS),
)
