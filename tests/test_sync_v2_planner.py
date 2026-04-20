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
