"""The four fixed D3 checks in LLD 19.25, without another data-reading path.

The first request uses the existing literal source and real parameter SQL, but
fails during preparation before reading price rows. Its stop/clock control is
the existing explicit D3Control substitute. The other three functions only
construct contracts: their source_rows=21 is metadata, not 21 new input rows.
"""

from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timezone

import pytest

from d3_support import d3_data, request
from src.foundation.technical_indicators import CalculationInstance
from src.foundation.technical_indicators.contracts import CalculationStatistics
from src.foundation.technical_indicators.errors import OutputContractError, RequestInvalidError
from src.foundation.technical_indicators.output.contracts import (
    OutputFieldDescription, OutputInstanceDescription,
)
from src.foundation.technical_indicators.output.result import (
    build_calculation_result, normalize_read_range,
)
from src.foundation.technical_indicators.sources.contracts import SourceDescription


def test_one_unrepresentable_macd_component_rejects_before_price_rows(d3_data):
    state = d3_data
    with state.case("one_unrepresentable_macd_component_rejects_before_price_rows"):
        before = (state.input_rows, state.sql_rows, state.real_controls, state.fixture_rows)
        config = replace(state.config, goldenshare_lake_root=str(state.literal_root))
        selected = request((CalculationInstance("macd", "macd", {
            "fast": 12, "slow": 1152921504606846976, "signal": 9,
        }),), period="day", adjustment="none")
        with pytest.raises(RequestInvalidError) as caught:
            state.run(selected, real=False, config=config)
        call = state.calls[-1]
        assert call["status"] == "failed" and call["error_type"] == "RequestInvalidError"
        assert call["source_rows"] == 0 and call["batches"] == []
        assert call["live_tables"] == [] and call["live_arrow"] == []
        assert not getattr(caught.value, "__notes__", ())
        # A valid fast/signal component must not hide the invalid slow one.
        # No state/output/batch step may begin after the parameter rejection.
        assert tuple((item["step_name"], item["logical_input_rows"])
                     for item in call["steps"]) == (
            ("create_parameters", 3), ("read_smoothing_limits", 1),
        )
        assert call["sql_logical_rows"] == 4
        assert (state.input_rows, state.sql_rows, state.real_controls, state.fixture_rows) == (
            before[0], before[1] + 4, before[2], before[3],
        )


def test_output_description_copies_external_containers(d3_data):
    state = d3_data
    with state.case("output_description_copies_external_containers"):
        parameters = [["period", 20]]
        field = OutputFieldDescription("value", "DOUBLE", True, "前N−1位置NULL")
        fields = [field]
        description = OutputInstanceDescription("ma20", "ma", "1.0.0", parameters, fields)
        parameters[0][1] = 99
        parameters.append(["other", 1])
        fields.clear()
        assert description.parameters == (("period", 20),)
        assert description.fields == (field,)
        assert isinstance(description.parameters, tuple)
        assert isinstance(description.parameters[0], tuple)
        assert isinstance(description.fields, tuple)
        with pytest.raises(FrozenInstanceError):
            description.instance_id = "changed"
        with pytest.raises(FrozenInstanceError):
            field.name = "changed"


def test_read_range_rejects_internal_handoff_errors(d3_data):
    state = d3_data
    with state.case("read_range_rejects_internal_handoff_errors"):
        selected = request(period="day", adjustment="none")
        statistics = CalculationStatistics(21, 0, 0, 0, 1, 0, 0.0)
        first, last = date(2026, 1, 5), date(2026, 2, 2)
        assert normalize_read_range(
            request=selected, statistics=replace(statistics, source_rows=0),
            read_start=None, read_end=None,
        ) == (None, None)
        assert normalize_read_range(
            request=selected, statistics=statistics, read_start=first, read_end=last,
        ) == (first, last)
        minute = request(period="1m", adjustment="none")
        normalized = normalize_read_range(
            request=minute, statistics=replace(statistics, source_rows=2),
            read_start=datetime(2026, 10, 26, 10, 0),
            read_end=datetime(2026, 10, 26, 2, 1, tzinfo=timezone.utc),
        )
        assert tuple(value.isoformat() for value in normalized) == (
            "2026-10-26T10:00:00+08:00", "2026-10-26T10:01:00+08:00",
        )
        assert normalized[0] < normalized[1]
        # Exactly the five already approved internal-handoff errors, not a
        # Cartesian product of dates, periods or source quantities.
        for rows, read_start, read_end, reason in (
            (21, None, last, "wrong_batch"),
            (21, None, None, "wrong_batch"),
            (21, last, first, "wrong_batch"),
            (0, first, last, "wrong_batch"),
            (21, datetime(2026, 1, 5), last, "type_mismatch"),
        ):
            with pytest.raises(OutputContractError) as caught:
                normalize_read_range(
                    request=selected, statistics=replace(statistics, source_rows=rows),
                    read_start=read_start, read_end=read_end,
                )
            assert caught.value.reason == reason
            assert caught.value.stage == "final_query"


def test_unknown_global_dates_are_not_inferred_from_read_range(d3_data):
    state = d3_data
    with state.case("unknown_global_dates_are_not_inferred_from_read_range"):
        selected = request((CalculationInstance("ma20", "ma", {}),),
                           period="day", adjustment="none", start=date(2026, 2, 3))
        field = OutputFieldDescription("value", "DOUBLE", True, "前N−1位置NULL")
        instances = (OutputInstanceDescription(
            "ma20", "ma", "1.0.0", (("period", 20),), (field,),
        ),)
        # A pure source-description literal, not a source implementation or a
        # claim that another set of Lake files has been read.
        source = SourceDescription(
            source_id="contract_only", contract_version="1", input_adjustment="none",
            basis_rule=None, basis_date=None, basis_value=None,
            price_unit="CNY", volume_unit="lot", amount_unit="thousand_CNY",
            timezone="Asia/Shanghai", period_label_rule="period_start",
            history_origin_rule="source_start", available_through=None,
            supports_partial_period=True, supported_adjustment_paths=(("none", "none"),),
            converted=False,
        )
        statistics = CalculationStatistics(21, 0, 21, 0, 1, 0, 0.0)
        arguments = dict(
            request=selected, instances=instances, statistics=statistics, rows=(),
            columns=("seq", "trade_date", "period_start", "period_end", "source_as_of", "value_0_0"),
            value_columns=(("value_0_0",),),
            read_start=date(2026, 1, 5), read_end=date(2026, 2, 2),
        )
        result = build_calculation_result(description=source, **arguments)
        assert result.source.history_start is None and result.source.available_through is None
        assert (result.source.read_start, result.source.read_end) == (
            date(2026, 1, 5), date(2026, 2, 2),
        )
        assert result.statistics.source_rows == 21
        assert result.times == () and result.source_as_of is None
        assert result.range.count == 0
        assert result.range.actual_start is result.range.actual_end is None
        assert result.msg == ""
        assert result.calculations[0].fields == (("value", ()),)
        declared = build_calculation_result(
            description=replace(source, available_through=date(2026, 2, 5)), **arguments,
        )
        assert declared.source.history_start is None
        assert declared.source.available_through == date(2026, 2, 5)
        assert declared.source.available_through != declared.source.read_end
        assert declared.source.read_start == result.source.read_start
        assert declared.source.read_end == result.source.read_end
