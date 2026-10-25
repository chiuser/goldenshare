"""BOLL adds SQL population deviation to its declared window-mean dependency."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import ClassVar

from ...contracts import Parameters, _freeze_parameters
from ..calculation import CalculationDefinition, CalculationOutput, Dependency, OutputField, ParameterSpec, SqlStep
from ..history import HistoryRequirement
from ..sql_templates import render_sql

DEFINITION = CalculationDefinition(
    calculation_id="boll", algorithm_version="1.0.0", description="布林带，使用总体标准差stddev_pop",
    parameter_specs=(ParameterSpec("period", "positive_integer", 20), ParameterSpec("multiplier", "finite_nonnegative", 2)),
    input_fields=frozenset({"close"}),
    output_fields=tuple(OutputField(name, name, "DOUBLE", True, "不足N根三个NULL；N=1标准差0") for name in ("middle", "upper", "lower")),
    initialization="不足完整窗口时NULL", history_rule="首输出前需要period−1根；同窗均值依赖复用",
    units=tuple((name, "source_price_unit") for name in ("middle", "upper", "lower")),
)


@dataclass(frozen=True, slots=True)
class BollingerBandsCalculation:
    parameters: Parameters

    TABLE_ROLES: ClassVar = MappingProxyType({"output": ("ti_boll_output", "batch")})
    SQL_FILES: ClassVar = ("bollinger_bands.sql",)
    FIXED_SQL_STEPS: ClassVar = MappingProxyType({})
    SQL_PACKAGE: ClassVar = "src.foundation.technical_indicators.calculation"

    def __post_init__(self):
        object.__setattr__(self, "parameters", _freeze_parameters(self.parameters))

    def input_requirement(self):
        return HistoryRequirement(DEFINITION.input_fields, dict(self.parameters)["period"] - 1,
                                  False, (), DEFINITION.initialization)

    def dependencies(self):
        return (Dependency("mean", "window_mean", "1.0.0",
                           (("period", dict(self.parameters)["period"]),)),)

    def prepare(self, session):
        pass

    def consume(self, batch, session):
        values = dict(self.parameters)
        output = session.declare_owned_table("output")
        mean = session.dependencies["mean"].table_name
        sql = render_sql(session.sql_templates["bollinger_bands.sql"],
                         tables={"price": batch.table_name, "mean": mean, "output": output},
                         integers={"window_preceding": values["period"] - 1})
        session.execute(SqlStep("bollinger_bands", sql,
                                (values["period"], batch.new_first_seq, batch.new_last_seq,
                                 values["multiplier"], values["multiplier"]),
                                (batch.table_name, mean), (output,),
                                batch.new_row_count + batch.history_rows + batch.new_row_count))
        return CalculationOutput(output, DEFINITION.output_fields,
                                 batch.new_first_seq, batch.new_last_seq)

    def release_batch(self, session):
        for name in tuple(reversed(session.batch_tables)):
            session.drop_owned_table(name)

    def release(self, session):
        for name in tuple(reversed(session.batch_tables)):
            session.drop_owned_table(name, cleanup=True)
