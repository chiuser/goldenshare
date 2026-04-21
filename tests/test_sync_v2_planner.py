from __future__ import annotations

from dataclasses import replace
from datetime import date
from types import SimpleNamespace

import pytest

from src.foundation.services.sync_v2.contracts import RunRequest
from src.foundation.services.sync_v2.errors import SyncV2PlanningError
from src.foundation.services.sync_v2.planner import SyncV2Planner
from src.foundation.services.sync_v2.registry import get_sync_v2_contract
from src.foundation.services.sync_v2.validator import ContractValidator


def _build_margin_range_request() -> RunRequest:
    return RunRequest(
        request_id="req-margin-range",
        dataset_key="margin",
        run_profile="range_rebuild",
        trigger_source="manual",
        params={"start_date": "20260401", "end_date": "20260402"},
    )


def test_planner_expands_trade_dates_and_enum_fanout(mocker) -> None:
    session = mocker.Mock()
    planner = SyncV2Planner(session)
    planner.dao = SimpleNamespace(
        trade_calendar=SimpleNamespace(
            get_open_dates=lambda exchange, start_date, end_date: [
                date(2026, 4, 1),
                date(2026, 4, 2),
            ]
        )
    )

    contract = get_sync_v2_contract("margin")
    validated = ContractValidator().validate(
        request=_build_margin_range_request(),
        contract=contract,
        strict=True,
    )

    units = planner.plan(validated, contract)

    assert len(units) == 6
    assert {unit.request_params["exchange_id"] for unit in units} == {"SSE", "SZSE", "BSE"}
    assert {unit.trade_date for unit in units} == {date(2026, 4, 1), date(2026, 4, 2)}


def test_planner_week_end_and_month_end_compress() -> None:
    open_dates = [
        date(2026, 4, 6),
        date(2026, 4, 8),
        date(2026, 4, 10),
        date(2026, 4, 14),
        date(2026, 4, 29),
        date(2026, 4, 30),
        date(2026, 5, 29),
    ]

    assert SyncV2Planner._compress_to_week_end(open_dates) == [
        date(2026, 4, 10),
        date(2026, 4, 14),
        date(2026, 4, 30),
        date(2026, 5, 29),
    ]
    assert SyncV2Planner._compress_to_month_end(open_dates) == [
        date(2026, 4, 30),
        date(2026, 5, 29),
    ]


def test_planner_rejects_when_planned_units_exceed_limit(mocker) -> None:
    session = mocker.Mock()
    planner = SyncV2Planner(session)
    planner.dao = SimpleNamespace(
        trade_calendar=SimpleNamespace(
            get_open_dates=lambda exchange, start_date, end_date: [
                date(2026, 4, 1),
                date(2026, 4, 2),
            ]
        )
    )

    contract = get_sync_v2_contract("margin")
    limited_contract = replace(
        contract,
        planning_spec=replace(contract.planning_spec, max_units_per_execution=1),
    )
    validated = ContractValidator().validate(
        request=_build_margin_range_request(),
        contract=limited_contract,
        strict=True,
    )

    with pytest.raises(SyncV2PlanningError) as exc_info:
        planner.plan(validated, limited_contract)

    assert exc_info.value.structured_error.error_code == "units_exceeded"


def test_planner_dc_member_fanout_uses_dc_index_board_pool(mocker) -> None:
    session = mocker.Mock()
    session.scalars.return_value = ["BK1184.DC", "BK0999.DC"]
    planner = SyncV2Planner(session)
    planner.dao = SimpleNamespace(
        trade_calendar=SimpleNamespace(
            get_open_dates=lambda exchange, start_date, end_date: [date(2026, 4, 21)]
        )
    )
    contract = get_sync_v2_contract("dc_member")
    request = RunRequest(
        request_id="req-dc-member",
        dataset_key="dc_member",
        run_profile="point_incremental",
        trigger_source="manual",
        params={"trade_date": "20260421"},
    )
    validated = ContractValidator().validate(request=request, contract=contract, strict=True)

    units = planner.plan(validated, contract)

    assert len(units) == 2
    assert {unit.request_params["ts_code"] for unit in units} == {"BK1184.DC", "BK0999.DC"}
    assert {unit.trade_date for unit in units} == {date(2026, 4, 21)}


def test_planner_dc_member_fanout_falls_back_to_source_when_dc_index_empty(mocker) -> None:
    session = mocker.Mock()
    session.scalars.return_value = []
    planner = SyncV2Planner(session)
    planner.dao = SimpleNamespace(
        trade_calendar=SimpleNamespace(
            get_open_dates=lambda exchange, start_date, end_date: [date(2026, 4, 21)]
        )
    )
    connector = mocker.Mock()
    connector.call.return_value = [
        {"ts_code": "BK2001.DC"},
        {"ts_code": "BK2002.DC"},
    ]
    mocker.patch("src.foundation.services.sync_v2.planner.create_source_connector", return_value=connector)
    contract = get_sync_v2_contract("dc_member")
    request = RunRequest(
        request_id="req-dc-member-fallback",
        dataset_key="dc_member",
        run_profile="point_incremental",
        trigger_source="manual",
        params={"trade_date": "20260421"},
    )
    validated = ContractValidator().validate(request=request, contract=contract, strict=True)

    units = planner.plan(validated, contract)

    assert len(units) == 2
    assert {unit.request_params["ts_code"] for unit in units} == {"BK2001.DC", "BK2002.DC"}
    connector.call.assert_called_once()


def test_planner_index_daily_fanout_uses_active_index_pool(mocker) -> None:
    session = mocker.Mock()
    planner = SyncV2Planner(session)
    planner.dao = SimpleNamespace(
        index_series_active=SimpleNamespace(list_active_codes=lambda resource: ["000001.SH", "399001.SZ"]),
        index_basic=SimpleNamespace(get_active_indexes=lambda: []),
    )
    contract = get_sync_v2_contract("index_daily")
    request = RunRequest(
        request_id="req-index-daily",
        dataset_key="index_daily",
        run_profile="point_incremental",
        trigger_source="manual",
        params={"trade_date": "20260421"},
    )
    validated = ContractValidator().validate(request=request, contract=contract, strict=True)

    units = planner.plan(validated, contract)

    assert len(units) == 2
    assert {unit.request_params["ts_code"] for unit in units} == {"000001.SH", "399001.SZ"}
    assert {unit.request_params["trade_date"] for unit in units} == {"20260421"}


def test_planner_index_daily_range_rebuild_uses_start_end_with_active_pool(mocker) -> None:
    session = mocker.Mock()
    planner = SyncV2Planner(session)
    planner.dao = SimpleNamespace(
        index_series_active=SimpleNamespace(list_active_codes=lambda resource: []),
        index_basic=SimpleNamespace(
            get_active_indexes=lambda: [
                SimpleNamespace(ts_code="000001.SH"),
                SimpleNamespace(ts_code="399001.SZ"),
            ]
        ),
    )
    contract = get_sync_v2_contract("index_daily")
    request = RunRequest(
        request_id="req-index-daily-range",
        dataset_key="index_daily",
        run_profile="range_rebuild",
        trigger_source="manual",
        params={"start_date": "20260415", "end_date": "20260417"},
    )
    validated = ContractValidator().validate(request=request, contract=contract, strict=True)

    units = planner.plan(validated, contract)

    assert len(units) == 2
    assert {unit.request_params["ts_code"] for unit in units} == {"000001.SH", "399001.SZ"}
    assert {unit.request_params["start_date"] for unit in units} == {"20260415"}
    assert {unit.request_params["end_date"] for unit in units} == {"20260417"}
