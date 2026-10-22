"""MA definition; no Python indicator formula or execution placeholder."""

from ..calculation import CalculationDefinition, OutputField, ParameterSpec

DEFINITION = CalculationDefinition(
    calculation_id="ma", algorithm_version="1.0.0", description="收盘价移动平均",
    parameter_specs=(ParameterSpec("period", "positive_integer", 20),),
    input_fields=frozenset({"close"}),
    output_fields=(OutputField("value", "value", "DOUBLE", True, "前N−1位置NULL；N=1为close"),),
    initialization="不足完整窗口时NULL", history_rule="首输出前需要period−1根；按当前K线对齐",
    units=(("value", "source_price_unit"),),
)
