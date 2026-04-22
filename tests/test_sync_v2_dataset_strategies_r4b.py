from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from src.foundation.services.sync_v2.contracts import RunRequest
from src.foundation.services.sync_v2.dataset_strategies.index_monthly import build_index_monthly_units
from src.foundation.services.sync_v2.dataset_strategies.index_weekly import build_index_weekly_units
from src.foundation.services.sync_v2.registry import get_sync_v2_contract
from src.foundation.services.sync_v2.validator import ContractValidator


def test_index_weekly_strategy_fans_out_active_pool_on_point_incremental() -> None:
    contract = get_sync_v2_contract("index_weekly")
    request = RunRequest(
        request_id="req-index-weekly-strategy-point",
        dataset_key="index_weekly",
        run_profile="point_incremental",
        trigger_source="manual",
        params={"trade_date": "20260417"},
    )
    validated = ContractValidator().validate(request=request, contract=contract, strict=True)
    dao = SimpleNamespace(
        index_series_active=SimpleNamespace(list_active_codes=lambda resource: ["000001.SH", "399001.SZ"]),
        index_basic=SimpleNamespace(get_active_indexes=lambda: []),
        trade_calendar=SimpleNamespace(get_open_dates=lambda exchange, start_date, end_date: []),
    )
    settings = SimpleNamespace(default_exchange="SSE")

    units = build_index_weekly_units(validated, contract, dao=dao, settings=settings, session=None)

    assert len(units) == 2
    assert {unit.request_params["ts_code"] for unit in units} == {"000001.SH", "399001.SZ"}
    assert {unit.request_params["trade_date"] for unit in units} == {"20260417"}
    assert {unit.page_limit for unit in units} == {1000}


def test_index_monthly_strategy_range_rebuild_uses_month_end_anchors() -> None:
    contract = get_sync_v2_contract("index_monthly")
    request = RunRequest(
        request_id="req-index-monthly-strategy-range",
        dataset_key="index_monthly",
        run_profile="range_rebuild",
        trigger_source="manual",
        params={"start_date": "20260401", "end_date": "20260531"},
    )
    validated = ContractValidator().validate(request=request, contract=contract, strict=True)
    dao = SimpleNamespace(
        index_series_active=SimpleNamespace(list_active_codes=lambda resource: []),
        index_basic=SimpleNamespace(
            get_active_indexes=lambda: [SimpleNamespace(ts_code="000300.SH"), SimpleNamespace(ts_code="000905.SH")]
        ),
        trade_calendar=SimpleNamespace(
            get_open_dates=lambda exchange, start_date, end_date: [
                date(2026, 4, 29),
                date(2026, 4, 30),
                date(2026, 5, 28),
                date(2026, 5, 29),
            ]
        ),
    )
    settings = SimpleNamespace(default_exchange="SSE")

    units = build_index_monthly_units(validated, contract, dao=dao, settings=settings, session=None)

    assert len(units) == 4
    assert {unit.request_params["ts_code"] for unit in units} == {"000300.SH", "000905.SH"}
    assert {unit.request_params["start_date"] for unit in units} == {"20260401"}
    assert {unit.request_params["end_date"] for unit in units} == {"20260531"}
    assert {unit.trade_date for unit in units} == {date(2026, 4, 30), date(2026, 5, 29)}
