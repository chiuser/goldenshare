"""MA borrows a request-local window mean computed only once in SQL."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import ClassVar

from ...contracts import Parameters, _freeze_parameters
from ..calculation import CalculationDefinition, CalculationOutput, Dependency, OutputField, ParameterSpec, SqlStep
from ..history import HistoryRequirement
from ..sql_templates import render_sql

DEFINITION = CalculationDefinition(
    calculation_id="ma", algorithm_version="1.0.0", description="收盘价移动平均",
    parameter_specs=(ParameterSpec("period", "positive_integer", 20),),
    input_fields=frozenset({"close"}),
    output_fields=(OutputField("value", "value", "DOUBLE", True, "前N−1位置NULL；N=1为close"),),
    initialization="不足完整窗口时NULL", history_rule="首输出前需要period−1根；按当前K线对齐",
    units=(("value", "source_price_unit"),),
)

WINDOW_MEAN_DEFINITION = CalculationDefinition(
    calculation_id="window_mean", algorithm_version="1.0.0", public=False,
    description="同窗完整收盘价均值，供MA和BOLL只读复用",
    parameter_specs=DEFINITION.parameter_specs, input_fields=DEFINITION.input_fields,
    output_fields=DEFINITION.output_fields, initialization=DEFINITION.initialization,
    history_rule=DEFINITION.history_rule, units=DEFINITION.units,
)


@dataclass(frozen=True, slots=True)
class WindowMeanCalculation:
    parameters: Parameters

    TABLE_ROLES: ClassVar = MappingProxyType({"output": ("ti_mean", "batch")})
    SQL_FILES: ClassVar = ("rolling_mean.sql",)
    FIXED_SQL_STEPS: ClassVar = MappingProxyType({})
    SQL_PACKAGE: ClassVar = "src.foundation.technical_indicators.calculation"

    def __post_init__(self):
        object.__setattr__(self, "parameters", _freeze_parameters(self.parameters))

    def input_requirement(self):
        return HistoryRequirement(DEFINITION.input_fields, dict(self.parameters)["period"] - 1,
                                  False, (), DEFINITION.initialization)

    def dependencies(self):
        return ()

    def prepare(self, session):
        pass

    def consume(self, batch, session):
        period = dict(self.parameters)["period"]
        output = session.declare_owned_table("output")
        sql = render_sql(session.sql_templates["rolling_mean.sql"],
                         tables={"price": batch.table_name, "output": output},
                         integers={"window_preceding": period - 1})
        session.execute(SqlStep("rolling_mean", sql,
                                (period, batch.new_first_seq, batch.new_last_seq),
                                (batch.table_name,), (output,),
                                batch.new_row_count + batch.history_rows))
        return CalculationOutput(output, WINDOW_MEAN_DEFINITION.output_fields,
                                 batch.new_first_seq, batch.new_last_seq)

    def release_batch(self, session):
        for name in tuple(reversed(session.batch_tables)):
            session.drop_owned_table(name)

    def release(self, session):
        for name in tuple(reversed(session.batch_tables)):
            session.drop_owned_table(name, cleanup=True)


@dataclass(frozen=True, slots=True)
class MovingAverageCalculation:
    parameters: Parameters

    TABLE_ROLES: ClassVar = MappingProxyType({})
    SQL_FILES: ClassVar = ()
    FIXED_SQL_STEPS: ClassVar = MappingProxyType({})
    SQL_PACKAGE: ClassVar = "src.foundation.technical_indicators.calculation"

    def __post_init__(self):
        object.__setattr__(self, "parameters", _freeze_parameters(self.parameters))

    def input_requirement(self):
        return HistoryRequirement(DEFINITION.input_fields, dict(self.parameters)["period"] - 1,
                                  False, (), DEFINITION.initialization)

    def dependencies(self):
        return (Dependency("mean", "window_mean", "1.0.0", self.parameters),)

    def prepare(self, session):
        pass

    def consume(self, batch, session):
        mean = session.dependencies["mean"]
        return CalculationOutput(mean.table_name, DEFINITION.output_fields,
                                 batch.new_first_seq, batch.new_last_seq)

    def release_batch(self, session):
        pass

    def release(self, session):
        pass
