"""MACD with SQL coefficients, safe segments, and request-local SQL state."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import ClassVar

from ...contracts import Parameters, _freeze_parameters
from ...errors import CalculationExecutionError, ResourceCleanupError
from ..calculation import CalculationDefinition, CalculationOutput, ControlReadStep, OutputField, ParameterSpec, SqlStep
from ..history import HistoryRequirement
from ..sql_templates import render_sql

DEFINITION = CalculationDefinition(
    calculation_id="macd", algorithm_version="1.0.0", description="两EMA、DIF、DEA及两倍差值柱",
    parameter_specs=(ParameterSpec("fast", "positive_integer", 12), ParameterSpec("slow", "positive_integer", 26), ParameterSpec("signal", "positive_integer", 9)),
    input_fields=frozenset({"close"}),
    output_fields=tuple(OutputField(name, name, "DOUBLE", False, "首条DIF/DEA/柱严格0") for name in ("dif", "dea", "hist")),
    initialization="首个close初始化两EMA，DEA为0", history_rule="从来源约定起点递推；展示/分页不重置",
    units=tuple((name, "source_price_unit") for name in ("dif", "dea", "hist")),
    parameter_relations=(("fast", "slow"),),
)


@dataclass(frozen=True, slots=True)
class MACDCalculation:
    parameters: Parameters

    SQL_PACKAGE: ClassVar = "src.foundation.technical_indicators.calculation"
    TABLE_ROLES: ClassVar = MappingProxyType({
        "parameters": ("ti_macd_parameters", "state"),
        "state": ("ti_macd_state", "state"),
        "work": ("ti_macd_work", "batch"),
        "output": ("ti_macd_output", "batch"),
    })
    SQL_FILES: ClassVar = ("smoothing_parameters.sql", "macd_first.sql", "macd_segment.sql")
    FIXED_SQL_STEPS: ClassVar = MappingProxyType({
        "create_parameters": """CREATE TEMP TABLE {{parameters}} AS
            WITH f AS ({{smoothing}}), s AS ({{smoothing}}), g AS ({{smoothing}})
            SELECT f.n AS fast, s.n AS slow, g.n AS signal,
                   f.alpha AS af, f.beta AS bf, s.alpha AS aslow, s.beta AS bslow,
                   g.alpha AS ag, g.beta AS bg,
                   CASE WHEN f.safe_rows IS NULL OR s.safe_rows IS NULL OR g.safe_rows IS NULL
                        THEN NULL ELSE least(f.safe_rows,s.safe_rows,g.safe_rows) END::INTEGER AS segment_rows
            FROM f CROSS JOIN s CROSS JOIN g""",
        "create_state": """CREATE TEMP TABLE {{state}} (
            last_seq BIGINT, origin_price DOUBLE,
            ema_fast_offset DOUBLE, ema_slow_offset DOUBLE, dea DOUBLE)""",
        "create_output": "CREATE TEMP TABLE {{output}} (seq BIGINT, dif DOUBLE, dea DOUBLE, hist DOUBLE)",
        "macd_first_output": """INSERT INTO {{output}}
            SELECT last_seq AS seq, 0.0 AS dif, 0.0 AS dea, 0.0 AS hist FROM {{state}}""",
        "append_segment": "INSERT INTO {{output}} SELECT seq, dif, dea, hist FROM {{work}}",
        "update_state": """UPDATE {{state}} SET
            last_seq=w.seq, ema_fast_offset=w.ef, ema_slow_offset=w.es, dea=w.dea
            FROM (SELECT seq,ef,es,dea FROM {{work}} ORDER BY seq DESC LIMIT 1) w""",
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
        return HistoryRequirement(DEFINITION.input_fields, 0, True,
            ("last_seq", "origin_price", "ema_fast_offset", "ema_slow_offset", "dea"),
            DEFINITION.initialization)

    def dependencies(self):
        return ()

    @staticmethod
    def _check_count(stats, expected):
        if stats.output_rows != expected:
            error = CalculationExecutionError(f"MACD {stats.step_name} produced an unexpected row count")
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
            (values["fast"], "ema", values["slow"], "ema", values["signal"], "ema"),
            (), (parameters,), 3)), 1)
        session.read_control_row("read_smoothing_limits")
        state = session.declare_owned_table("state")
        session.execute(SqlStep("create_state",
            render_sql(self.FIXED_SQL_STEPS["create_state"], tables={"state": state}),
            (), (), (state,), 0))

    def consume(self, batch, session):
        output = session.declare_owned_table("output")
        state = session.table_roles["state"][0]
        parameters = session.table_roles["parameters"][0]
        session.execute(SqlStep("create_output",
            render_sql(self.FIXED_SQL_STEPS["create_output"], tables={"output": output}),
            (), (), (output,), 0))
        input_rows = batch.new_row_count + batch.history_rows
        if not session.initialized:
            self._check_count(session.execute(SqlStep("macd_first",
                render_sql(session.sql_templates["macd_first.sql"], tables={"price": batch.table_name, "state": state}),
                (batch.new_first_seq,), (batch.table_name,), (state,), input_rows)), 1)
            self._check_count(session.execute(SqlStep("macd_first_output",
                render_sql(self.FIXED_SQL_STEPS["macd_first_output"], tables={"state": state, "output": output}),
                (), (state,), (output,), 1)), 1)
            session.initialized = True
            expected_last = batch.new_first_seq
        else:
            expected_last = batch.new_first_seq - 1
        while True:
            last_seq, next_end, segment_rows = session.read_control_row("read_segment_bounds", (batch.new_last_seq,))
            if last_seq != expected_last:
                error = CalculationExecutionError("MACD state does not match the current batch progress")
                error.step_name = "read_segment_bounds"
                error.reason = "control_bounds"
                raise error
            if segment_rows == 0:
                break
            work = session.declare_owned_table("work")
            self._check_count(session.execute(SqlStep("macd_segment",
                render_sql(session.sql_templates["macd_segment.sql"], tables={"price": batch.table_name,
                    "state": state, "parameters": parameters, "work": work}),
                (next_end,), (batch.table_name, state, parameters), (work,), input_rows + 2)), segment_rows)
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
            error = ResourceCleanupError("MACD resources could not all be released")
            for exc in errors:
                error.add_note(f"{type(exc).__name__}: {exc}")
            raise error from errors[0]
