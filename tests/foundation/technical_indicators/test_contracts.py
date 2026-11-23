"""Independent literal contracts from frozen LLD §04/05/09/14/19.2.

No data source or mathematical implementation is substituted by these tests.
"""

from dataclasses import FrozenInstanceError, fields, replace
from datetime import date, datetime, timezone
import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from goldenshare_technical_indicators import CalculationRequest
from goldenshare_technical_indicators.contracts import (
    CalculationResult, CalculationValues, normalize_request_and_validate_all_instances,
)
from goldenshare_technical_indicators.errors import (
    CalculationUnsupportedError, RequestInvalidError, ResourceLimitError,
)


def request(**kwargs):
    values = dict(security_type="stock", ts_code="600000.SH", period="day",
                  adjustment="none",
                  start=datetime(2026, 10, 23, tzinfo=timezone.utc),
                  end=datetime(2026, 10, 24, tzinfo=timezone.utc),
                  calculations=({"calculation_id": "macd", "parameters": {}},))
    return CalculationRequest(**(values | kwargs))


def test_each_adjustment_is_structurally_valid_and_request_fields_follow_the_range_mode():
    for adjustment in ("none", "qfq", "hfq"):
        assert request(adjustment=adjustment).adjustment == adjustment
    original = request()
    values = {field.name: getattr(original, field.name) for field in fields(CalculationRequest)}
    required = {"security_type", "ts_code", "period", "adjustment", "end", "calculations"}
    assert set(values) == required | {"start", "latest_rows"}
    for field in required:
        with pytest.raises(TypeError):
            CalculationRequest(**{key: value for key, value in values.items() if key != field})
    del values["start"]
    with pytest.raises(RequestInvalidError, match="timezone-aware"):
        CalculationRequest(**values)
    assert CalculationRequest(**(values | {"latest_rows": 2})).start is None


@pytest.mark.parametrize("kwargs", [
    {"adjustment": ["qfq", "hfq"]}, {"adjustment": "bad"},
    {"security_type": "fund"}, {"ts_code": "600000"}, {"period": "year"},
    {"calculations": ()},
    {"calculations": ("macd",)},
    {"calculations": ({"calculation_id": "ma", "parameters": {}, "instance_id": "custom"},)},
    {"calculations": ({"calculation_id": "ma"},)},
])
def test_invalid_request_fails_without_io(kwargs):
    with pytest.raises(RequestInvalidError):
        request(**kwargs)


def test_unknown_request_options_and_budget_override_rejected():
    for key in ("bars", "sql", "allow_gap", "source_path", "max_output_rows", "basis_date", "before", "limit"):
        with pytest.raises(TypeError):
            request(**{key: 1})


@pytest.mark.parametrize("period", ("day", "week", "month", "1m", "5m", "15m", "30m", "60m", "90m", "120m"))
def test_time_contract_requires_aware_bounds_for_every_period(period):
    instant = datetime(2026, 10, 22, 16, 0, tzinfo=timezone.utc)
    assert request(period=period, start=instant).start.isoformat() == "2026-10-23T00:00:00+08:00"
    assert request(period=period, start=instant, end=instant).start == instant
    for field in ("start", "end"):
        for value in (date(2026, 10, 23), datetime(2026, 10, 23), None):
            with pytest.raises(RequestInvalidError, match="timezone-aware"):
                request(period=period, **{field: value})
    with pytest.raises(RequestInvalidError, match="start must not exceed end"):
        request(period=period, end=instant)


def test_calculation_records_are_independent_and_immutable():
    original = {"fast": 9}
    item = {"calculation_id": "macd", "parameters": original}
    items = [item]
    directive = request(calculations=items)
    item["calculation_id"] = "ma"
    items.clear()
    original["fast"] = 100
    assert directive.calculations == ({"calculation_id": "macd", "parameters": {"fast": 9}},)
    with pytest.raises(TypeError):
        directive.calculations[0]["parameters"]["fast"] = 10
    with pytest.raises(TypeError):
        directive.calculations[0]["calculation_id"] = "other"
    with pytest.raises(FrozenInstanceError):
        directive.period = "week"
    for value in (float("inf"), float("nan"), [], {}):
        with pytest.raises(RequestInvalidError):
            request(calculations=({"calculation_id": "ma", "parameters": {"period": value}},))


def test_capacity_bound_checks_requested_items_before_planning():
    config = SimpleNamespace(max_indicator_instances=16)
    item = {"calculation_id": "ma", "parameters": {}}
    instances = (item,) * 16
    original = request(calculations=instances)
    assert normalize_request_and_validate_all_instances(original, config) is original
    with pytest.raises(ResourceLimitError):
        normalize_request_and_validate_all_instances(request(calculations=instances + (item,)), config)


@pytest.mark.parametrize("module,identifier,parameters,outputs", [
    ("price", "price", (), ("open", "high", "low", "close", "volume", "amount")),
    ("moving_average", "ma", (("period", 20),), ("value",)),
    ("bollinger_bands", "boll", (("period", 20), ("multiplier", 2)), ("middle", "upper", "lower")),
    ("macd", "macd", (("fast", 12), ("slow", 26), ("signal", 9)), ("dif", "dea", "hist")),
    ("kdj", "kdj", (("window", 9), ("k_period", 3), ("d_period", 3)), ("k", "d", "j")),
])
def test_five_definitions_match_independent_lld_literals(module, identifier, parameters, outputs):
    definition = importlib.import_module("goldenshare_technical_indicators.calculation.indicators." + module).DEFINITION
    assert definition.calculation_id == identifier
    assert definition.validate_parameters({}) == parameters
    assert tuple(field.name for field in definition.output_fields) == outputs
    assert definition.algorithm_version == ("2.0.0" if identifier in {"macd", "kdj"} else "1.0.0")
    assert definition.supported_periods == ("1m", "5m", "15m", "30m", "60m", "90m", "120m", "day", "week", "month")
    assert all(field.sql_type == "DOUBLE" for field in definition.output_fields)
    assert definition.public is True
    # Independent input, initialization-NULL and unit contracts from LLD §05/09.
    expected_inputs = {
        "price": {"open", "high", "low", "close", "volume", "amount"},
        "ma": {"close"}, "boll": {"close"}, "macd": {"close"},
        "kdj": {"high", "low", "close"},
    }
    expected_nullable = {
        "price": (False, False, False, False, True, True), "ma": (True,),
        "boll": (True, True, True), "macd": (False, False, False), "kdj": (False, False, False),
    }
    expected_units = {
        "price": (("open", "source_price_unit"), ("high", "source_price_unit"),
                  ("low", "source_price_unit"), ("close", "source_price_unit"),
                  ("volume", "source_volume_unit"), ("amount", "source_amount_unit")),
        "ma": (("value", "source_price_unit"),),
        "boll": (("middle", "source_price_unit"), ("upper", "source_price_unit"), ("lower", "source_price_unit")),
        "macd": (("dif", "source_price_unit"), ("dea", "source_price_unit"), ("hist", "source_price_unit")),
        "kdj": (("k", "dimensionless"), ("d", "dimensionless"), ("j", "dimensionless")),
    }
    assert definition.input_fields == frozenset(expected_inputs[identifier])
    assert tuple(field.nullable for field in definition.output_fields) == expected_nullable[identifier]
    assert definition.units == expected_units[identifier]
    with pytest.raises(CalculationUnsupportedError):
        definition.validate_parameters({"not_declared": 1})


def test_parameter_rules_allow_real_variations_without_period_or_multiplier_cap():
    from goldenshare_technical_indicators.calculation.indicators.moving_average import DEFINITION as ma
    from goldenshare_technical_indicators.calculation.indicators.bollinger_bands import DEFINITION as boll
    from goldenshare_technical_indicators.calculation.indicators.macd import DEFINITION as macd

    assert ma.validate_parameters({"period": 10001}) == (("period", 10001),)
    for multiplier in (0, 11):
        assert boll.validate_parameters({"multiplier": multiplier}) == (("period", 20), ("multiplier", multiplier))
    assert macd.validate_parameters({"fast": 9, "slow": 65}) == (("fast", 9), ("slow", 65), ("signal", 9))
    for value in (True, 0, -1, 1.5, "20", None):
        with pytest.raises(RequestInvalidError):
            ma.validate_parameters({"period": value})
    for value in (True, -1, float("nan"), float("inf")):
        with pytest.raises(RequestInvalidError):
            boll.validate_parameters({"multiplier": value})
    for fast, slow in ((26, 26), (27, 26)):
        with pytest.raises(RequestInvalidError):
            macd.validate_parameters({"fast": fast, "slow": slow})


def test_result_contract_matches_literal_top_level_and_copies_mutable_field_inputs():
    assert tuple(field.name for field in fields(CalculationResult)) == (
        "kernel_version", "series", "requested", "source", "price_adjustment", "times", "source_as_of", "calculations", "range", "statistics", "msg",
        "period_bars",
    )
    source_values = [None, 11.0]
    values = CalculationValues("ma", "1.0.0", (("period", 2),), (("value", source_values),))
    assert tuple(field.name for field in fields(CalculationValues)) == (
        "calculation_id", "algorithm_version", "parameters", "fields",
    )
    source_values.append(99.0)
    assert values.fields == (("value", (None, 11.0)),)
    with pytest.raises(FrozenInstanceError):
        values.algorithm_version = "other"


def test_d1_has_no_fake_calculation_or_source_import_side_effects():
    import goldenshare_technical_indicators as package
    from goldenshare_technical_indicators.calculation import calculation

    assert not hasattr(package, "calculate")
    assert not hasattr(package, "CalculationInstance")
    assert "OutputField" in vars(calculation)
    assert "OutputField" not in vars(importlib.import_module(package.__name__ + ".contracts"))
    # D3 publishes the complete service operation, while keeping the package
    # free of a global calculate function and import-time database resources.
    from goldenshare_technical_indicators.service import TechnicalIndicatorService
    assert callable(TechnicalIndicatorService.calculate)


def test_dependency_copies_both_parameter_container_levels():
    """LLD §19.4: modifying the original input must not change a declaration."""
    from goldenshare_technical_indicators.calculation.calculation import Dependency

    parameters = [["period", 20]]
    dependency = Dependency("mean", "window_mean", "1.0.0", parameters)
    parameters[0][1] = 99
    parameters.append(["other", 1])
    assert dependency.parameters == (("period", 20),)


def test_sql_step_copies_binding_and_table_name_containers():
    from goldenshare_technical_indicators.calculation.calculation import SqlStep

    bindings, inputs, outputs = [20, date(2026, 10, 23), None], ["prices"], ["mean"]
    step = SqlStep("mean", "SELECT ?", bindings, inputs, outputs, 3)
    bindings[0] = 99
    inputs.append("unexpected")
    outputs.clear()
    assert step.bindings == (20, date(2026, 10, 23), None)
    assert step.input_tables == ("prices",)
    assert step.output_tables == ("mean",)


def test_output_descriptions_copy_fields_and_instance_pairs():
    from goldenshare_technical_indicators.calculation.calculation import (
        BatchCalculationOutputs, CalculationOutput, OutputField,
    )
    from goldenshare_technical_indicators.sources.contracts import PriceBatch

    field = OutputField("value", "value", "DOUBLE", True, "First N-1 positions NULL")
    fields_input = [field]
    output = CalculationOutput("ma_output", fields_input, 1, 3)
    fields_input.clear()
    assert output.fields == (field,)
    price = PriceBatch("prices", 1, 3, 3, 0, ("trade_date",), ("close",), "qfq")
    instances = [[0, output]]
    batch = BatchCalculationOutputs(price, instances)
    instances[0][0] = 1
    instances.clear()
    assert batch.instances == ((0, output),)
    for bad_index in ("ma20", -1, False):
        with pytest.raises(ValueError, match="calculation index"):
            BatchCalculationOutputs(price, ((bad_index, output),))


def test_node_and_discovery_descriptions_copy_their_container_inputs():
    from goldenshare_technical_indicators.calculation.dependencies import CalculationNode
    from goldenshare_technical_indicators.calculation.indicators.moving_average import DEFINITION
    from goldenshare_technical_indicators.discovery.catalog import CalculationDescription, SourceCapability

    parameters = [["period", 20]]
    node = CalculationNode(0, DEFINITION, parameters, object(), {})
    parameters[0][1] = 99
    assert node.parameters == (("period", 20),)
    capability = SourceCapability("stock", "day", "qfq", "declared_source")
    source_input = [capability]
    description = CalculationDescription(DEFINITION, source_input, True)
    source_input.clear()
    assert description.source_capabilities == (capability,)


@pytest.mark.parametrize("value", [[], {}, {"value"}, (1, 2)])
def test_sql_step_rejects_non_scalar_binding_instead_of_retaining_mutable_data(value):
    from goldenshare_technical_indicators.calculation.calculation import SqlStep

    with pytest.raises(ValueError, match="scalar"):
        SqlStep("invalid", "SELECT ?", (value,), (), (), 0)


@pytest.mark.parametrize("parameters", [[["period", []]], [["period", True]], [["period"]]])
def test_normalized_parameter_contract_rejects_mutable_or_malformed_values(parameters):
    from goldenshare_technical_indicators.calculation.calculation import Dependency

    with pytest.raises(RequestInvalidError):
        Dependency("mean", "window_mean", "1.0.0", parameters)


def test_immutable_tuple_inputs_and_ordinary_sql_scalars_remain_valid():
    from goldenshare_technical_indicators.calculation.calculation import Dependency, SqlStep

    assert Dependency("mean", "window_mean", "1.0.0", (("period", 20),)).parameters == (("period", 20),)
    values = (1, 2.5, True, "value", date(2026, 10, 23), datetime(2026, 10, 23, 10), None)
    assert SqlStep("valid", "SELECT ?", values, ("prices",), ("output",), 1).bindings == values
