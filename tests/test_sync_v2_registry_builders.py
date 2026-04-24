from __future__ import annotations

from src.foundation.services.sync_v2.contracts import InputField
from src.foundation.services.sync_v2.registry_parts.builders import (
    build_date_model,
    build_input_schema,
    build_normalization_spec,
    build_planning_spec,
    build_write_spec,
)


def test_build_input_schema_normalizes_fields_to_tuple() -> None:
    schema = build_input_schema(
        fields=[
            InputField("trade_date", "date", required=False, description="交易日"),
            InputField("ts_code", "string", required=False, description="代码"),
        ]
    )

    assert isinstance(schema.fields, tuple)
    assert tuple(field.name for field in schema.fields) == ("trade_date", "ts_code")


def test_build_planning_spec_keeps_planning_values() -> None:
    planning = build_planning_spec(
        universe_policy="none",
        pagination_policy="none",
    )

    assert planning.universe_policy == "none"
    assert planning.pagination_policy == "none"


def test_build_date_model_returns_registered_dataset_model() -> None:
    model = build_date_model("daily")

    assert model.date_axis == "trade_open_day"
    assert model.bucket_rule == "every_open_day"
    assert model.observed_field == "trade_date"


def test_build_normalization_spec_normalizes_iterables_to_tuples() -> None:
    spec = build_normalization_spec(
        date_fields=["trade_date"],
        decimal_fields=["open", "close"],
        required_fields=["trade_date", "ts_code"],
    )

    assert spec.date_fields == ("trade_date",)
    assert spec.decimal_fields == ("open", "close")
    assert spec.required_fields == ("trade_date", "ts_code")


def test_build_write_spec_normalizes_conflict_columns_to_tuple() -> None:
    spec = build_write_spec(
        raw_dao_name="raw_suspend_d",
        core_dao_name="equity_suspend_d",
        target_table="core_serving.equity_suspend_d",
        conflict_columns=["row_key_hash"],
    )

    assert spec.raw_dao_name == "raw_suspend_d"
    assert spec.core_dao_name == "equity_suspend_d"
    assert spec.target_table == "core_serving.equity_suspend_d"
    assert spec.conflict_columns == ("row_key_hash",)
