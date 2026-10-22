"""KDJ definition, keeping initialization and historical requirements explicit."""

from ..calculation import CalculationDefinition, OutputField, ParameterSpec

DEFINITION = CalculationDefinition(
    calculation_id="kdj", algorithm_version="1.0.0", description="高低窗口、RSV及K/D/J",
    parameter_specs=(ParameterSpec("window", "positive_integer", 9), ParameterSpec("k_period", "positive_integer", 3), ParameterSpec("d_period", "positive_integer", 3)),
    input_fields=frozenset({"high", "low", "close"}),
    output_fields=tuple(OutputField(name, name, "DOUBLE", False, "窗口不足使用已有行；平区间RSV=50") for name in ("k", "d", "j")),
    initialization="递推前K=D=50", history_rule="窗口需要window−1根；K/D从来源起点递推",
    units=tuple((name, "dimensionless") for name in ("k", "d", "j")),
)
