from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion.execution_plan import DatasetActionRequest, DatasetTimeInput
from src.foundation.ingestion.unit_planner import DatasetUnitPlanner
from src.foundation.ingestion.validator import DatasetRequestValidator


def _validated_request(*, dataset_key: str, run_profile: str, time_input: DatasetTimeInput, filters: dict | None = None):
    definition = get_dataset_definition(dataset_key)
    request = DatasetActionRequest(
        dataset_key=dataset_key,
        action="maintain",
        time_input=time_input,
        filters=filters or {},
    )
    validated = DatasetRequestValidator().validate(
        request=request,
        definition=definition,
        run_profile=run_profile,
    )
    return definition, validated


def test_planner_expands_dc_member_board_pool_from_dc_index_snapshot(mocker) -> None:
    session = mocker.Mock()
    session.scalars.return_value = ["BK001", "BK002"]
    planner = DatasetUnitPlanner(session)

    definition, validated = _validated_request(
        dataset_key="dc_member",
        run_profile="point_incremental",
        time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 4, 24)),
        filters={"idx_type": ["概念板块"]},
    )

    units = planner.plan(validated, definition)

    assert len(units) == 2
    assert {unit.request_params["ts_code"] for unit in units} == {"BK001", "BK002"}
    assert {unit.request_params["trade_date"] for unit in units} == {"20260424"}


def test_planner_expands_ths_member_board_pool_from_ths_index_snapshot(mocker) -> None:
    session = mocker.Mock()
    session.scalars.return_value = ["885001.TI", "885002.TI"]
    planner = DatasetUnitPlanner(session)

    definition, validated = _validated_request(
        dataset_key="ths_member",
        run_profile="snapshot_refresh",
        time_input=DatasetTimeInput(mode="none"),
    )

    units = planner.plan(validated, definition)

    assert len(units) == 2
    assert {unit.request_params["ts_code"] for unit in units} == {"885001.TI", "885002.TI"}


def test_planner_compresses_trade_dates_to_month_end() -> None:
    open_dates = [
        date(2026, 4, 1),
        date(2026, 4, 29),
        date(2026, 4, 30),
        date(2026, 5, 6),
        date(2026, 5, 29),
    ]

    assert DatasetUnitPlanner._compress_to_month_end(open_dates) == [
        date(2026, 4, 30),
        date(2026, 5, 29),
    ]
