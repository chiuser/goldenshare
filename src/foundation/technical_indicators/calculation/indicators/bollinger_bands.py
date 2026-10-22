"""BOLL definition using the same window mean as MA in D3."""

from ..calculation import CalculationDefinition, OutputField, ParameterSpec

DEFINITION = CalculationDefinition(
    calculation_id="boll", algorithm_version="1.0.0", description="布林带，使用总体标准差stddev_pop",
    parameter_specs=(ParameterSpec("period", "positive_integer", 20), ParameterSpec("multiplier", "finite_nonnegative", 2)),
    input_fields=frozenset({"close"}),
    output_fields=tuple(OutputField(name, name, "DOUBLE", True, "不足N根三个NULL；N=1标准差0") for name in ("middle", "upper", "lower")),
    initialization="不足完整窗口时NULL", history_rule="首输出前需要period−1根；同窗均值依赖复用",
    units=tuple((name, "source_price_unit") for name in ("middle", "upper", "lower")),
)
