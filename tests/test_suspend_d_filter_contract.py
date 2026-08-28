from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion import (
    DatasetActionRequest,
    DatasetActionResolver,
    DatasetTimeInput,
)
from src.foundation.ingestion.errors import IngestionValidationError
from src.foundation.ingestion.request_builders import _suspend_d_params


def test_suspend_d_definition_declares_suspend_type_fanout() -> None:
    definition = get_dataset_definition("suspend_d")
    suspend_type = next(
        field
        for field in definition.input_model.filters
        if field.name == "suspend_type"
    )

    assert suspend_type.multi_value is True
    assert suspend_type.enum_values == ("S", "R")
    assert definition.planning.enum_fanout_fields == ("suspend_type",)
    assert definition.planning.enum_fanout_defaults == {}


def test_suspend_d_point_without_type_keeps_one_unfiltered_unit(mocker) -> None:
    plan = DatasetActionResolver(mocker.Mock()).build_plan(
        DatasetActionRequest(
            dataset_key="suspend_d",
            action="maintain",
            time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 8, 27)),
        )
    )

    assert plan.planning.unit_count == 1
    assert plan.units[0].request_params == {"trade_date": "20260827"}
    assert plan.units[0].pagination_policy == "offset_limit"
    assert plan.units[0].page_limit == 5000


@pytest.mark.parametrize("selected_type", ("S", ["R"]))
def test_suspend_d_point_sends_one_valid_selected_type(mocker, selected_type) -> None:  # type: ignore[no-untyped-def]
    plan = DatasetActionResolver(mocker.Mock()).build_plan(
        DatasetActionRequest(
            dataset_key="suspend_d",
            action="maintain",
            time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 8, 27)),
            filters={"suspend_type": selected_type},
        )
    )

    expected_type = (
        selected_type if isinstance(selected_type, str) else selected_type[0]
    )
    assert plan.planning.unit_count == 1
    assert plan.units[0].request_params == {
        "trade_date": "20260827",
        "suspend_type": expected_type,
    }


def test_suspend_d_point_fans_out_s_and_r_without_list_stringification(mocker) -> None:
    plan = DatasetActionResolver(mocker.Mock()).build_plan(
        DatasetActionRequest(
            dataset_key="suspend_d",
            action="maintain",
            time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 8, 27)),
            filters={"suspend_type": ["S", "R"]},
        )
    )

    assert plan.planning.unit_count == 2
    assert {unit.request_params["suspend_type"] for unit in plan.units} == {"S", "R"}
    assert all(
        isinstance(unit.request_params["suspend_type"], str) for unit in plan.units
    )
    assert all(unit.request_params["suspend_type"] in {"S", "R"} for unit in plan.units)


def test_suspend_d_range_fans_out_each_open_day_and_selected_type(mocker) -> None:
    fake_dao = SimpleNamespace(
        trade_calendar=SimpleNamespace(
            get_open_dates=mocker.Mock(
                return_value=[date(2026, 8, 26), date(2026, 8, 27)]
            )
        )
    )
    mocker.patch(
        "src.foundation.ingestion.unit_planner.DAOFactory", return_value=fake_dao
    )

    plan = DatasetActionResolver(mocker.Mock()).build_plan(
        DatasetActionRequest(
            dataset_key="suspend_d",
            action="maintain",
            time_input=DatasetTimeInput(
                mode="range",
                start_date=date(2026, 8, 25),
                end_date=date(2026, 8, 27),
            ),
            filters={"suspend_type": ["S", "R"]},
        )
    )

    assert plan.planning.unit_count == 4
    assert [
        (unit.trade_date, unit.request_params["suspend_type"]) for unit in plan.units
    ] == [
        (date(2026, 8, 26), "R"),
        (date(2026, 8, 26), "S"),
        (date(2026, 8, 27), "R"),
        (date(2026, 8, 27), "S"),
    ]
    assert {unit.page_limit for unit in plan.units} == {5000}
    fake_dao.trade_calendar.get_open_dates.assert_called_once_with(
        "SSE", date(2026, 8, 25), date(2026, 8, 27)
    )


def test_suspend_d_rejects_unknown_type_before_planning(mocker) -> None:
    with pytest.raises(IngestionValidationError, match="停复牌类型不在可选范围内：X"):
        DatasetActionResolver(mocker.Mock()).build_plan(
            DatasetActionRequest(
                dataset_key="suspend_d",
                action="maintain",
                time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 8, 27)),
                filters={"suspend_type": ["S", "X"]},
            )
        )


def test_suspend_d_request_builder_rejects_unexpanded_multi_value() -> None:
    request = SimpleNamespace(params={"suspend_type": ["S", "R"]})

    with pytest.raises(ValueError, match="必须由 planner 按单值展开"):
        _suspend_d_params(request, date(2026, 8, 27), {})
