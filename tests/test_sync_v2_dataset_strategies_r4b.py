from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from src.foundation.services.sync_v2.contracts import RunRequest
from src.foundation.services.sync_v2.dataset_strategies.index_monthly import build_index_monthly_units
from src.foundation.services.sync_v2.dataset_strategies.index_weekly import build_index_weekly_units
from src.foundation.services.sync_v2.registry import get_sync_v2_contract
from src.foundation.services.sync_v2.validator import ContractValidator


def test_index_weekly_strategy_builds_trade_date_unit_without_ts_code_by_default() -> None:
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
        trade_calendar=SimpleNamespace(get_open_dates=lambda exchange, start_date, end_date: []),
    )
    settings = SimpleNamespace(default_exchange="SSE")

    units = build_index_weekly_units(validated, contract, dao=dao, settings=settings, session=None)

    assert len(units) == 1
    assert units[0].request_params.get("ts_code") is None
    assert {unit.request_params["trade_date"] for unit in units} == {"20260417"}
    assert {unit.page_limit for unit in units} == {1000}


def test_index_monthly_strategy_range_rebuild_uses_month_end_trade_date_units() -> None:
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

    assert len(units) == 2
    assert {unit.request_params["trade_date"] for unit in units} == {"20260430", "20260529"}
    assert {unit.request_params.get("ts_code") for unit in units} == {None}
    assert {unit.trade_date for unit in units} == {date(2026, 4, 30), date(2026, 5, 29)}
