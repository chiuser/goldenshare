from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from src.foundation.services.sync_v2.contracts import RunRequest
from src.foundation.services.sync_v2.dataset_strategies.limit_list_d import build_limit_list_d_units
from src.foundation.services.sync_v2.registry import get_sync_v2_contract
from src.foundation.services.sync_v2.validator import ContractValidator


def _fake_dao(open_dates: list[date]) -> SimpleNamespace:
    return SimpleNamespace(
        trade_calendar=SimpleNamespace(get_open_dates=lambda exchange, start, end: open_dates)
    )


def test_limit_list_d_point_incremental_with_single_filters() -> None:
    contract = get_sync_v2_contract("limit_list_d")
    request = RunRequest(
        request_id="req-limit-list-point-single",
        dataset_key="limit_list_d",
        run_profile="point_incremental",
        trigger_source="test",
        trade_date=date(2026, 4, 3),
        params={"limit_type": "U", "exchange": "SH"},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_limit_list_d_units(validated, contract, dao=_fake_dao([]), settings=SimpleNamespace(default_exchange="SSE"), session=None)

    assert len(units) == 1
    assert units[0].request_params == {"trade_date": "20260403", "limit_type": "U", "exchange": "SH"}
    assert units[0].pagination_policy == "offset_limit"
    assert units[0].page_limit == 2500


def test_limit_list_d_point_incremental_default_request_expands_real_enum_units() -> None:
    contract = get_sync_v2_contract("limit_list_d")
    request = RunRequest(
        request_id="req-limit-list-point-default",
        dataset_key="limit_list_d",
        run_profile="point_incremental",
        trigger_source="test",
        trade_date=date(2026, 4, 3),
        params={},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_limit_list_d_units(validated, contract, dao=_fake_dao([]), settings=SimpleNamespace(default_exchange="SSE"), session=None)

    assert len(units) == 9
    combos = {(unit.request_params["limit_type"], unit.request_params["exchange"]) for unit in units}
    assert combos == {
        ("U", "SH"),
        ("U", "SZ"),
        ("U", "BJ"),
        ("D", "SH"),
        ("D", "SZ"),
        ("D", "BJ"),
        ("Z", "SH"),
        ("Z", "SZ"),
        ("Z", "BJ"),
    }
    assert {unit.request_params["trade_date"] for unit in units} == {"20260403"}


def test_limit_list_d_range_rebuild_fans_out_dates_and_filters() -> None:
    contract = get_sync_v2_contract("limit_list_d")
    request = RunRequest(
        request_id="req-limit-list-range",
        dataset_key="limit_list_d",
        run_profile="range_rebuild",
        trigger_source="test",
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 2),
        params={"limit_type": "D", "exchange": "BJ"},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_limit_list_d_units(
        validated,
        contract,
        dao=_fake_dao([date(2026, 3, 1), date(2026, 3, 2)]),
        settings=SimpleNamespace(default_exchange="SSE"),
        session=None,
    )

    assert len(units) == 2
    assert units[0].request_params == {"trade_date": "20260301", "limit_type": "D", "exchange": "BJ"}
    assert units[1].request_params == {"trade_date": "20260302", "limit_type": "D", "exchange": "BJ"}
