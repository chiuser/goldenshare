"""Nine-turn uses shared closes and carries a single capped count between batches."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import ClassVar

from ...contracts import Parameters
from ...sources.contracts import PriceBatch
from ..calculation import (
    CalculationDefinition, CalculationOutput, CalculationSession, Dependency, OutputField, SqlStep,
)
from ..history import HistoryRequirement
from ..sql_templates import render_sql


DEFINITION = CalculationDefinition(
    calculation_id="nineturn",
    algorithm_version="1.0.0",
    description="比较前第 4 根收盘价的连续九转计数，最高为 13",
    parameter_specs=(),
    input_fields=frozenset({"close"}),
    output_fields=(
        OutputField("up_count", "up_count", "DOUBLE", False, "无可比较的收盘价时为 0"),
        OutputField("down_count", "down_count", "DOUBLE", False, "无可比较的收盘价时为 0"),
    ),
    initialization="行情起点方向和计数均为 0",
    history_rule="首根目标前最多 16 根，批次之间保留前 4 根收盘价",
    units=(("up_count", "count"), ("down_count", "count")),
    supported_periods=("day",),
    additional_sources=(
        ("stock", "week", "qfq"), ("stock", "month", "qfq"),
        ("stock", "30m", "qfq"), ("stock", "60m", "qfq"),
    ),
)


@dataclass(frozen=True, slots=True)
class NineTurnCalculation:
    parameters: Parameters

    SQL_PACKAGE: ClassVar = "goldenshare_technical_indicators.calculation"
    TABLE_ROLES: ClassVar = MappingProxyType({
        "state": ("ti_nineturn_state", "state"),
        "output": ("ti_nineturn_output", "batch"),
    })
    SQL_FILES: ClassVar = ("nineturn_batch.sql",)
    FIXED_SQL_STEPS: ClassVar = MappingProxyType({
        "create_state": "CREATE TEMP TABLE {{state}} (direction INTEGER, count INTEGER)",
        "initialize_state": "INSERT INTO {{state}} VALUES (0, 0)",
        "update_state": """
            UPDATE {{state}}
            SET direction = CASE WHEN tail.up_count > 0 THEN 1 WHEN tail.down_count > 0 THEN -1 ELSE 0 END,
                count = greatest(tail.up_count, tail.down_count)::INTEGER
            FROM (SELECT up_count, down_count FROM {{output}} ORDER BY seq DESC LIMIT 1) AS tail
        """,
    })

    def input_requirement(self, session: CalculationSession, max_input_rows: int) -> HistoryRequirement:
        return HistoryRequirement(
            DEFINITION.input_fields, 4, 16, False, ("direction", "count"), DEFINITION.initialization,
        )

    def dependencies(self) -> tuple[Dependency, ...]:
        return ()

    def prepare(self, session: CalculationSession) -> None:
        state = session.declare_owned_table("state")
        for name in ("create_state", "initialize_state"):
            sql = render_sql(self.FIXED_SQL_STEPS[name], tables={"state": state})
            session.execute(SqlStep(name, sql, (), (), (state,), 0))

    def consume(self, batch: PriceBatch, session: CalculationSession) -> CalculationOutput:
        state = session.table_roles["state"][0]
        output = session.declare_owned_table("output")
        sql = render_sql(session.sql_templates["nineturn_batch.sql"],
                         tables={"price": batch.table_name, "state": state, "output": output})
        session.execute(SqlStep(
            "nineturn_batch", sql, (batch.new_first_seq, batch.new_last_seq),
            (batch.table_name, state), (output,), batch.new_row_count + batch.history_rows + 1,
        ))
        update = render_sql(self.FIXED_SQL_STEPS["update_state"], tables={"state": state, "output": output})
        session.execute(SqlStep("update_state", update, (), (output, state), (state,), batch.new_row_count + 1))
        return CalculationOutput(output, DEFINITION.output_fields, batch.new_first_seq, batch.new_last_seq)

    def release_batch(self, session: CalculationSession) -> None:
        for table in tuple(session.batch_tables):
            session.drop_owned_table(table)

    def release(self, session: CalculationSession) -> None:
        for table in (*session.batch_tables, *session.state_tables):
            session.drop_owned_table(table, cleanup=True)
