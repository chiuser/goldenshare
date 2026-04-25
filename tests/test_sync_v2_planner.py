from __future__ import annotations

from dataclasses import replace
from datetime import date
from types import SimpleNamespace

import pytest

from src.foundation.services.sync_v2.contracts import RunRequest
from src.foundation.services.sync_v2.dataset_strategies.index_daily import build_index_daily_units
from src.foundation.services.sync_v2.dataset_strategies.stk_mins import build_stk_mins_units
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


def test_index_daily_strategy_range_rebuild_uses_start_end_with_active_pool(mocker) -> None:
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

    units = build_index_daily_units(validated, contract, planner.dao, planner.settings, session)

    assert len(units) == 2
    assert {unit.request_params["ts_code"] for unit in units} == {"000001.SH", "399001.SZ"}
    assert {unit.request_params["start_date"] for unit in units} == {"20260415"}
    assert {unit.request_params["end_date"] for unit in units} == {"20260417"}


def test_planner_broker_recommend_range_rebuild_compresses_to_month_end(mocker) -> None:
    session = mocker.Mock()
    planner = SyncV2Planner(session)
    planner.dao = SimpleNamespace(
        trade_calendar=SimpleNamespace(
            get_open_dates=lambda exchange, start_date, end_date: [
                date(2026, 4, 29),
                date(2026, 4, 30),
                date(2026, 5, 28),
                date(2026, 5, 29),
            ]
        )
    )
    contract = get_sync_v2_contract("broker_recommend")
    request = RunRequest(
        request_id="req-broker-range",
        dataset_key="broker_recommend",
        run_profile="range_rebuild",
        trigger_source="manual",
        params={"start_date": "20260401", "end_date": "20260531"},
    )
    validated = ContractValidator().validate(request=request, contract=contract, strict=True)

    units = planner.plan(validated, contract)

    assert len(units) == 2
    assert {unit.trade_date for unit in units} == {date(2026, 4, 30), date(2026, 5, 29)}
    assert {unit.request_params["month"] for unit in units} == {"202604", "202605"}


def test_planner_broker_recommend_point_incremental_with_month_key_keeps_single_unit(mocker) -> None:
    session = mocker.Mock()
    planner = SyncV2Planner(session)
    planner.dao = SimpleNamespace(
        trade_calendar=SimpleNamespace(get_open_dates=lambda exchange, start_date, end_date: [])
    )
    contract = get_sync_v2_contract("broker_recommend")
    request = RunRequest(
        request_id="req-broker-point-month",
        dataset_key="broker_recommend",
        run_profile="point_incremental",
        trigger_source="manual",
        params={"month": "202604"},
    )
    validated = ContractValidator().validate(request=request, contract=contract, strict=True)

    units = planner.plan(validated, contract)

    assert len(units) == 1
    assert units[0].trade_date is None
    assert units[0].request_params["month"] == "202604"


def test_planner_trade_cal_range_rebuild_uses_single_natural_window(mocker) -> None:
    session = mocker.Mock()
    planner = SyncV2Planner(session)
    planner.dao = SimpleNamespace(
        trade_calendar=SimpleNamespace(
            get_open_dates=lambda exchange, start_date, end_date: [
                date(2026, 4, 1),
                date(2026, 4, 2),
                date(2026, 4, 3),
            ]
        )
    )
    contract = get_sync_v2_contract("trade_cal")
    request = RunRequest(
        request_id="req-trade-cal-range",
        dataset_key="trade_cal",
        run_profile="range_rebuild",
        trigger_source="manual",
        params={"start_date": "20260401", "end_date": "20260403"},
    )
    validated = ContractValidator().validate(request=request, contract=contract, strict=True)

    units = planner.plan(validated, contract)

    assert len(units) == 1
    assert units[0].trade_date is None
    assert units[0].request_params["start_date"] == "20260401"
    assert units[0].request_params["end_date"] == "20260403"


def test_stk_mins_strategy_expands_single_stock_freq_as_datetime_window(mocker) -> None:
    session = mocker.Mock()
    def _get_by_ts_code(ts_code: str):
        if ts_code == "600000.SH":
            return SimpleNamespace(name="浦发银行")
        return None

    dao = SimpleNamespace(
        security=SimpleNamespace(get_active_equities=lambda: [], get_by_ts_code=_get_by_ts_code),
        trade_calendar=SimpleNamespace(get_open_dates=lambda exchange, start_date, end_date: []),
    )
    contract = get_sync_v2_contract("stk_mins")
    request = RunRequest(
        request_id="req-stk-mins-point",
        dataset_key="stk_mins",
        run_profile="point_incremental",
        trigger_source="manual",
        params={"trade_date": "20260423", "ts_code": "600000.SH", "freq": ["30min", "60min"]},
    )
    validated = ContractValidator().validate(request=request, contract=contract, strict=True)

    units = build_stk_mins_units(validated, contract, dao, SimpleNamespace(default_exchange="SSE"), session)

    assert len(units) == 2
    assert {unit.request_params["ts_code"] for unit in units} == {"600000.SH"}
    assert {unit.request_params["freq"] for unit in units} == {"30min", "60min"}
    assert {unit.page_limit for unit in units} == {8000}
    assert {unit.request_params["start_date"] for unit in units} == {"2026-04-23 09:00:00"}
    assert {unit.request_params["end_date"] for unit in units} == {"2026-04-23 19:00:00"}
    assert {unit.progress_context["unit"] for unit in units} == {"stock"}
    assert {unit.progress_context["security_name"] for unit in units} == {"浦发银行"}


def test_stk_mins_strategy_uses_full_tushare_stock_pool(mocker) -> None:
    session = mocker.Mock()
    dao = SimpleNamespace(
        security=SimpleNamespace(
            get_active_equities=lambda: [
                SimpleNamespace(ts_code="600519.SH", source="tushare"),
                SimpleNamespace(ts_code="000001.SZ", source="tushare", name="平安银行"),
                SimpleNamespace(ts_code="BIYING_ONLY", source="biying"),
                SimpleNamespace(ts_code="600000.SH", source="tushare", name="浦发银行"),
            ]
        ),
        trade_calendar=SimpleNamespace(
            get_open_dates=lambda exchange, start_date, end_date: [
                date(2026, 4, 22),
                date(2026, 4, 23),
            ]
        ),
    )
    contract = get_sync_v2_contract("stk_mins")
    request = RunRequest(
        request_id="req-stk-mins-range",
        dataset_key="stk_mins",
        run_profile="range_rebuild",
        trigger_source="manual",
        params={"start_date": "20260422", "end_date": "20260423", "freq": "30min"},
    )
    validated = ContractValidator().validate(request=request, contract=contract, strict=True)

    units = build_stk_mins_units(validated, contract, dao, SimpleNamespace(default_exchange="SSE"), session)

    assert len(units) == 3
    assert {unit.trade_date for unit in units} == {None}
    assert {unit.request_params["ts_code"] for unit in units} == {"000001.SZ", "600000.SH", "600519.SH"}
    assert {unit.request_params["freq"] for unit in units} == {"30min"}
    assert {unit.request_params["start_date"] for unit in units} == {"2026-04-22 09:00:00"}
    assert {unit.request_params["end_date"] for unit in units} == {"2026-04-23 19:00:00"}
    assert any(unit.progress_context.get("security_name") == "平安银行" for unit in units)


def test_planner_ths_member_fanout_uses_ths_index_board_pool(mocker) -> None:
    session = mocker.Mock()
    session.scalars.return_value = ["885001.TI", "885002.TI"]
    planner = SyncV2Planner(session)
    planner.dao = SimpleNamespace(
        trade_calendar=SimpleNamespace(get_open_dates=lambda exchange, start_date, end_date: [])
    )
    contract = get_sync_v2_contract("ths_member")
    request = RunRequest(
        request_id="req-ths-member",
        dataset_key="ths_member",
        run_profile="point_incremental",
        trigger_source="manual",
        params={"trade_date": "20260421"},
    )
    validated = ContractValidator().validate(request=request, contract=contract, strict=True)

    units = planner.plan(validated, contract)

    assert len(units) == 2
    assert {unit.request_params["ts_code"] for unit in units} == {"885001.TI", "885002.TI"}


def test_planner_dc_daily_range_rebuild_uses_trade_date_anchors(mocker) -> None:
    session = mocker.Mock()
    planner = SyncV2Planner(session)
    planner.dao = SimpleNamespace(
        trade_calendar=SimpleNamespace(
            get_open_dates=lambda exchange, start_date, end_date: [
                date(2026, 4, 16),
                date(2026, 4, 17),
            ]
        )
    )
    contract = get_sync_v2_contract("dc_daily")
    request = RunRequest(
        request_id="req-dc-daily-range",
        dataset_key="dc_daily",
        run_profile="range_rebuild",
        trigger_source="manual",
        params={"start_date": "20260415", "end_date": "20260417"},
    )
    validated = ContractValidator().validate(request=request, contract=contract, strict=True)

    units = planner.plan(validated, contract)

    assert len(units) == 2
    assert [unit.request_params for unit in units] == [
        {"trade_date": "20260416"},
        {"trade_date": "20260417"},
    ]
