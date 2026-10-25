"""SQL high/low window and KDJ state; only new sequence positions recurse."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import ClassVar

from ...contracts import Parameters, _freeze_parameters
from ...errors import CalculationExecutionError, ResourceCleanupError
from ..calculation import CalculationDefinition, CalculationOutput, ControlReadStep, Dependency, OutputField, ParameterSpec, SqlStep
from ..history import HistoryRequirement
from ..sql_templates import render_sql

DEFINITION = CalculationDefinition(
    calculation_id="kdj", algorithm_version="1.0.0", description="高低窗口、RSV及K/D/J",
    parameter_specs=(ParameterSpec("window", "positive_integer", 9), ParameterSpec("k_period", "positive_integer", 3), ParameterSpec("d_period", "positive_integer", 3)),
    input_fields=frozenset({"high", "low", "close"}),
    output_fields=tuple(OutputField(name, name, "DOUBLE", False, "窗口不足使用已有行；平区间RSV=50") for name in ("k", "d", "j")),
    initialization="递推前K=D=50", history_rule="窗口需要window−1根；K/D从来源起点递推",
    units=tuple((name, "dimensionless") for name in ("k", "d", "j")),
)

WINDOW_RANGE_DEFINITION = CalculationDefinition(
    calculation_id="window_range", algorithm_version="1.0.0", public=False,
    description="最高最低窗口及RSV，只读供KDJ使用",
    parameter_specs=(ParameterSpec("window", "positive_integer", 9),),
    input_fields=DEFINITION.input_fields,
    output_fields=(OutputField("rsv", "rsv", "DOUBLE", False, "不足窗口使用已有行；平区间50"),),
    initialization="不足窗口使用已有行；平区间RSV=50",
    history_rule="首输出前需要window−1根", units=(("rsv", "dimensionless"),),
)


@dataclass(frozen=True, slots=True)
class WindowRangeCalculation:
    parameters: Parameters

    SQL_PACKAGE: ClassVar = "src.foundation.technical_indicators.calculation"
    TABLE_ROLES: ClassVar = MappingProxyType({"output": ("ti_range", "batch")})
    SQL_FILES: ClassVar = ("kdj_window.sql",)
    FIXED_SQL_STEPS: ClassVar = MappingProxyType({})

    def __post_init__(self):
        object.__setattr__(self, "parameters", _freeze_parameters(self.parameters))

    def input_requirement(self):
        return HistoryRequirement(DEFINITION.input_fields, dict(self.parameters)["window"] - 1,
                                  False, (), WINDOW_RANGE_DEFINITION.initialization)

    def dependencies(self):
        return ()

    def prepare(self, session):
        pass

    def consume(self, batch, session):
        window = dict(self.parameters)["window"]
        output = session.declare_owned_table("output")
        session.execute(SqlStep("kdj_window",
            render_sql(session.sql_templates["kdj_window.sql"],
                tables={"price": batch.table_name, "output": output},
                integers={"window_preceding": window - 1}),
            (batch.new_first_seq, batch.new_last_seq), (batch.table_name,), (output,),
            batch.new_row_count + batch.history_rows))
        return CalculationOutput(output, WINDOW_RANGE_DEFINITION.output_fields,
                                 batch.new_first_seq, batch.new_last_seq)

    def release_batch(self, session):
        for name in tuple(reversed(session.batch_tables)):
            session.drop_owned_table(name)

    def release(self, session):
        for name in tuple(reversed(session.batch_tables)):
            session.drop_owned_table(name, cleanup=True)


@dataclass(frozen=True, slots=True)
class KDJCalculation:
    parameters: Parameters

    SQL_PACKAGE: ClassVar = "src.foundation.technical_indicators.calculation"
    TABLE_ROLES: ClassVar = MappingProxyType({
        "parameters": ("ti_kdj_parameters", "state"),
        "state": ("ti_kdj_state", "state"),
        "work": ("ti_kdj_work", "batch"),
        "output": ("ti_kdj_output", "batch"),
    })
    SQL_FILES: ClassVar = ("smoothing_parameters.sql", "kdj_segment.sql")
    FIXED_SQL_STEPS: ClassVar = MappingProxyType({
        "create_parameters": """CREATE TEMP TABLE {{parameters}} AS
            WITH k AS ({{smoothing}}), d AS ({{smoothing}})
            SELECT k.n AS k_period,d.n AS d_period,k.alpha AS ak,k.beta AS bk,d.alpha AS ad,d.beta AS bd,
                CASE WHEN k.safe_rows IS NULL OR d.safe_rows IS NULL THEN NULL
                     ELSE least(k.safe_rows,d.safe_rows) END::INTEGER AS segment_rows
            FROM k CROSS JOIN d""",
        "create_state": "CREATE TEMP TABLE {{state}} (last_seq BIGINT,k DOUBLE,d DOUBLE)",
        "initialize_state": "INSERT INTO {{state}} VALUES (0,50.0,50.0)",
        "create_output": "CREATE TEMP TABLE {{output}} (seq BIGINT,k DOUBLE,d DOUBLE,j DOUBLE)",
        "append_segment": "INSERT INTO {{output}} SELECT seq,k,d,j FROM {{work}}",
        "update_state": """UPDATE {{state}} SET last_seq=w.seq,k=w.k,d=w.d
            FROM (SELECT seq,k,d FROM {{work}} ORDER BY seq DESC LIMIT 1) w""",
        "read_smoothing_limits": ControlReadStep(
            "SELECT segment_rows AS safe_rows FROM {{parameters}}",
            ("parameters",), (), (("safe_rows", "INTEGER"),), 1),
        "read_segment_bounds": ControlReadStep(
            """WITH endpoint AS (SELECT CAST(? AS BIGINT) AS new_last_seq), bounds AS (
                SELECT s.last_seq, least(s.last_seq+p.segment_rows,e.new_last_seq)::BIGINT AS next_end
                FROM {{state}} s CROSS JOIN {{parameters}} p CROSS JOIN endpoint e)
                SELECT last_seq,next_end,(next_end-last_seq)::INTEGER AS segment_rows FROM bounds""",
            ("state", "parameters"), (int,),
            (("last_seq", "BIGINT"), ("next_end", "BIGINT"), ("segment_rows", "INTEGER")), 2),
    })

    def __post_init__(self):
        object.__setattr__(self, "parameters", _freeze_parameters(self.parameters))

    def input_requirement(self):
        return HistoryRequirement(DEFINITION.input_fields, dict(self.parameters)["window"] - 1,
                                  True, ("last_seq", "k", "d"), DEFINITION.initialization)

    def dependencies(self):
        return (Dependency("range", "window_range", "1.0.0",
                           (("window", dict(self.parameters)["window"]),)),)

    @staticmethod
    def _check_count(stats, expected):
        if stats.output_rows != expected:
            error = CalculationExecutionError(f"KDJ {stats.step_name} produced an unexpected row count")
            error.step_name = stats.step_name
            error.reason = "output_count_mismatch"
            error.expected_rows = expected
            error.actual_rows = stats.output_rows
            raise error

    def prepare(self, session):
        parameters = session.declare_owned_table("parameters")
        smoothing = session.sql_templates["smoothing_parameters.sql"].rstrip().removesuffix(";")
        sql = self.FIXED_SQL_STEPS["create_parameters"].replace("{{smoothing}}", smoothing)
        values = dict(self.parameters)
        self._check_count(session.execute(SqlStep("create_parameters",
            render_sql(sql, tables={"parameters": parameters}),
            (values["k_period"], "kd", values["d_period"], "kd"), (), (parameters,), 2)), 1)
        session.read_control_row("read_smoothing_limits")
        state = session.declare_owned_table("state")
        session.execute(SqlStep("create_state",
            render_sql(self.FIXED_SQL_STEPS["create_state"], tables={"state": state}),
            (), (), (state,), 0))
        self._check_count(session.execute(SqlStep("initialize_state",
            render_sql(self.FIXED_SQL_STEPS["initialize_state"], tables={"state": state}),
            (), (), (state,), 0)), 1)
        session.initialized = True

    def consume(self, batch, session):
        output = session.declare_owned_table("output")
        state = session.table_roles["state"][0]
        parameters = session.table_roles["parameters"][0]
        range_table = session.dependencies["range"].table_name
        session.execute(SqlStep("create_output",
            render_sql(self.FIXED_SQL_STEPS["create_output"], tables={"output": output}),
            (), (), (output,), 0))
        expected_last = batch.new_first_seq - 1
        while True:
            last_seq, next_end, segment_rows = session.read_control_row("read_segment_bounds", (batch.new_last_seq,))
            if last_seq != expected_last:
                error = CalculationExecutionError("KDJ state does not match the current batch progress")
                error.step_name = "read_segment_bounds"
                error.reason = "control_bounds"
                raise error
            if segment_rows == 0:
                break
            work = session.declare_owned_table("work")
            self._check_count(session.execute(SqlStep("kdj_segment",
                render_sql(session.sql_templates["kdj_segment.sql"], tables={"range": range_table,
                    "state": state, "parameters": parameters, "work": work}),
                (next_end,), (range_table, state, parameters), (work,), batch.new_row_count + 2)), segment_rows)
            self._check_count(session.execute(SqlStep("append_segment",
                render_sql(self.FIXED_SQL_STEPS["append_segment"], tables={"output": output, "work": work}),
                (), (work,), (output,), segment_rows)), segment_rows)
            self._check_count(session.execute(SqlStep("update_state",
                render_sql(self.FIXED_SQL_STEPS["update_state"], tables={"state": state, "work": work}),
                (), (work, state), (state,), segment_rows + 1)), 1)
            session.drop_owned_table(work)
            expected_last = next_end
        return CalculationOutput(output, DEFINITION.output_fields, batch.new_first_seq, batch.new_last_seq)

    def release_batch(self, session):
        for name in tuple(reversed(session.batch_tables)):
            session.drop_owned_table(name)

    def release(self, session):
        errors = []
        for name in tuple(reversed((*session.state_tables, *session.batch_tables))):
            try:
                session.drop_owned_table(name, cleanup=True)
            except BaseException as exc:
                errors.append(exc)
        if errors:
            error = ResourceCleanupError("KDJ resources could not all be released")
            for exc in errors:
                error.add_note(f"{type(exc).__name__}: {exc}")
            raise error from errors[0]
