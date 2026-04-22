from __future__ import annotations

from types import SimpleNamespace

from src.foundation.services.sync_v2.contracts import RunRequest
from src.foundation.services.sync_v2.dataset_strategies.dividend import build_dividend_units
from src.foundation.services.sync_v2.dataset_strategies.index_weight import build_index_weight_units
from src.foundation.services.sync_v2.dataset_strategies.stk_holdernumber import build_stk_holdernumber_units
from src.foundation.services.sync_v2.registry import get_sync_v2_contract
from src.foundation.services.sync_v2.validator import ContractValidator


def test_dividend_strategy_fans_out_natural_dates_for_range_rebuild() -> None:
    contract = get_sync_v2_contract("dividend")
    request = RunRequest(
        request_id="req-dividend-strategy",
        dataset_key="dividend",
        run_profile="range_rebuild",
        trigger_source="manual",
        params={"start_date": "20260401", "end_date": "20260403"},
    )
    validated = ContractValidator().validate(request=request, contract=contract, strict=True)

    units = build_dividend_units(validated, contract, dao=None, settings=None, session=None)

    assert len(units) == 3
    assert [unit.request_params["ann_date"] for unit in units] == ["20260401", "20260402", "20260403"]
    assert {unit.pagination_policy for unit in units} == {"offset_limit"}
    assert {unit.page_limit for unit in units} == {6000}


def test_stk_holdernumber_strategy_uses_explicit_ann_date_as_single_unit() -> None:
    contract = get_sync_v2_contract("stk_holdernumber")
    request = RunRequest(
        request_id="req-holdernumber-strategy",
        dataset_key="stk_holdernumber",
        run_profile="range_rebuild",
        trigger_source="manual",
        params={"start_date": "20260401", "end_date": "20260430", "ann_date": "20260410"},
    )
    validated = ContractValidator().validate(request=request, contract=contract, strict=True)

    units = build_stk_holdernumber_units(validated, contract, dao=None, settings=None, session=None)

    assert len(units) == 1
    assert units[0].request_params["ann_date"] == "20260410"
    assert units[0].pagination_policy == "offset_limit"
    assert units[0].page_limit == 3000


def test_index_weight_strategy_fans_out_index_codes_from_active_pool() -> None:
    contract = get_sync_v2_contract("index_weight")
    request = RunRequest(
        request_id="req-index-weight-strategy",
        dataset_key="index_weight",
        run_profile="range_rebuild",
        trigger_source="manual",
        params={"start_date": "20260401", "end_date": "20260430"},
    )
    validated = ContractValidator().validate(request=request, contract=contract, strict=True)
    dao = SimpleNamespace(
        index_series_active=SimpleNamespace(list_active_codes=lambda dataset_key: ["000300.SH", "000905.SH"]),
        index_basic=SimpleNamespace(get_active_indexes=lambda: []),
    )

    units = build_index_weight_units(validated, contract, dao=dao, settings=None, session=None)

    assert len(units) == 2
    assert {unit.request_params["index_code"] for unit in units} == {"000300.SH", "000905.SH"}
    assert {unit.request_params["start_date"] for unit in units} == {"20260401"}
    assert {unit.request_params["end_date"] for unit in units} == {"20260430"}
