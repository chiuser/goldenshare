"""Four high/low EMA rails with fixed history and request-local SQL state."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import ClassVar

from ...contracts import Parameters, _freeze_parameters
from ...errors import CalculationExecutionError, ResourceCleanupError
from ..calculation import CalculationDefinition, CalculationOutput, ControlReadStep, OutputField, SqlStep
from ..history import HistoryRequirement
from ..sql_templates import render_sql


TREND_CHANNEL_WARMUP_ROWS = 500
_FIELDS = ("short_upper", "short_lower", "long_upper", "long_lower")

DEFINITION = CalculationDefinition(
    calculation_id="trend_channel", algorithm_version="1.0.0",
    description="最高价、最低价的25/90周期EMA四轨", parameter_specs=(),
    input_fields=frozenset({"high", "low"}),
    output_fields=tuple(OutputField(name, name, "DOUBLE", False, "首个最高价或最低价初始化") for name in _FIELDS),
    initialization="首个high初始化短长上轨，首个low初始化短长下轨；批次不重置",
    history_rule=f"首输出前固定预热{TREND_CHANNEL_WARMUP_ROWS}根；真实起点不足时使用已有历史",
    units=tuple((name, "source_price_unit") for name in _FIELDS),
)


@dataclass(frozen=True, slots=True)
class TrendChannelCalculation:
    parameters: Parameters

    SQL_PACKAGE: ClassVar = "goldenshare_technical_indicators.calculation"
    TABLE_ROLES: ClassVar = MappingProxyType({
        "parameters": ("ti_trend_channel_parameters", "state"),
        "state": ("ti_trend_channel_state", "state"),
        "work": ("ti_trend_channel_work", "batch"),
        "output": ("ti_trend_channel_output", "batch"),
    })
    SQL_FILES: ClassVar = ("smoothing_parameters.sql", "trend_channel_first.sql", "trend_channel_segment.sql")
    FIXED_SQL_STEPS: ClassVar = MappingProxyType({
        "create_parameters": """CREATE TEMP TABLE {{parameters}} AS
            WITH s AS ({{smoothing}}), l AS ({{smoothing}})
            SELECT s.alpha AS short_alpha, s.beta AS short_beta,
                   l.alpha AS long_alpha, l.beta AS long_beta,
                   least(s.safe_rows,l.safe_rows)::INTEGER AS segment_rows
            FROM s CROSS JOIN l""",
        "create_state": """CREATE TEMP TABLE {{state}} (
            last_seq BIGINT, short_upper DOUBLE, short_lower DOUBLE,
            long_upper DOUBLE, long_lower DOUBLE)""",
        "create_output": """CREATE TEMP TABLE {{output}} (
            seq BIGINT, short_upper DOUBLE, short_lower DOUBLE,
            long_upper DOUBLE, long_lower DOUBLE)""",
        "first_output": "INSERT INTO {{output}} SELECT * FROM {{state}}",
        "append_segment": "INSERT INTO {{output}} SELECT * FROM {{work}}",
        "update_state": """UPDATE {{state}} SET last_seq=w.seq,
            short_upper=w.short_upper,short_lower=w.short_lower,
            long_upper=w.long_upper,long_lower=w.long_lower
            FROM (SELECT * FROM {{work}} ORDER BY seq DESC LIMIT 1) w""",
        "read_smoothing_limits": ControlReadStep(
            "SELECT segment_rows AS safe_rows FROM {{parameters}}",
            ("parameters",), (), (("safe_rows", "INTEGER"),), 1),
        "read_segment_bounds": ControlReadStep(
            """WITH endpoint AS (SELECT CAST(? AS BIGINT) AS new_last_seq), bounds AS (
                SELECT s.last_seq,least(s.last_seq+p.segment_rows,e.new_last_seq)::BIGINT AS next_end
                FROM {{state}} s CROSS JOIN {{parameters}} p CROSS JOIN endpoint e)
                SELECT last_seq,next_end,(next_end-last_seq)::INTEGER AS segment_rows FROM bounds""",
            ("state", "parameters"), (int,),
            (("last_seq", "BIGINT"), ("next_end", "BIGINT"), ("segment_rows", "INTEGER")), 2),
    })

    def __post_init__(self):
        object.__setattr__(self, "parameters", _freeze_parameters(self.parameters))

    def input_requirement(self, session, max_input_rows):
        return HistoryRequirement(DEFINITION.input_fields, 0, TREND_CHANNEL_WARMUP_ROWS, False,
                                  ("last_seq", *_FIELDS), DEFINITION.initialization)

    def dependencies(self):
        return ()

    @staticmethod
    def _check_count(stats, expected):
        if stats.output_rows != expected:
            error = CalculationExecutionError(f"Trend channel {stats.step_name} produced an unexpected row count")
            error.step_name, error.reason = stats.step_name, "output_count_mismatch"
            error.expected_rows, error.actual_rows = expected, stats.output_rows
            raise error

    def prepare(self, session):
        parameters = session.declare_owned_table("parameters")
        smoothing = session.sql_templates["smoothing_parameters.sql"].rstrip().removesuffix(";")
        sql = self.FIXED_SQL_STEPS["create_parameters"].replace("{{smoothing}}", smoothing)
        self._check_count(session.execute(SqlStep("create_parameters",
            render_sql(sql, tables={"parameters": parameters}),
            (25, "ema", 90, "ema"), (), (parameters,), 2)), 1)
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
            self._check_count(session.execute(SqlStep("trend_channel_first",
                render_sql(session.sql_templates["trend_channel_first.sql"],
                           tables={"price": batch.table_name, "state": state}),
                (batch.new_first_seq,), (batch.table_name,), (state,), input_rows)), 1)
            self._check_count(session.execute(SqlStep("first_output",
                render_sql(self.FIXED_SQL_STEPS["first_output"], tables={"state": state, "output": output}),
                (), (state,), (output,), 1)), 1)
            session.initialized = True
            expected_last = batch.new_first_seq
        else:
            expected_last = batch.new_first_seq - 1
        while True:
            last_seq, next_end, segment_rows = session.read_control_row("read_segment_bounds", (batch.new_last_seq,))
            if last_seq != expected_last:
                error = CalculationExecutionError("Trend channel state does not match the current batch progress")
                error.step_name, error.reason = "read_segment_bounds", "control_bounds"
                raise error
            if segment_rows == 0:
                break
            work = session.declare_owned_table("work")
            self._check_count(session.execute(SqlStep("trend_channel_segment",
                render_sql(session.sql_templates["trend_channel_segment.sql"],
                           tables={"price": batch.table_name, "state": state, "parameters": parameters, "work": work}),
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
            error = ResourceCleanupError("Trend channel resources could not all be released")
            for exc in errors:
                error.add_note(f"{type(exc).__name__}: {exc}")
            raise error from errors[0]
