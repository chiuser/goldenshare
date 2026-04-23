from __future__ import annotations

from src.foundation.services.sync_v2.contracts import RunRequest
from src.foundation.services.sync_v2.dataset_strategies.hk_basic import build_hk_basic_units
from src.foundation.services.sync_v2.dataset_strategies.us_basic import build_us_basic_units
from src.foundation.services.sync_v2.registry import get_sync_v2_contract
from src.foundation.services.sync_v2.validator import ContractValidator


def test_build_hk_basic_units_supports_list_status_and_paging() -> None:
    contract = get_sync_v2_contract("hk_basic")
    request = RunRequest(
        request_id="req-hk-basic",
        dataset_key="hk_basic",
        run_profile="point_incremental",
        trigger_source="test",
        params={"list_status": ["L", "P"]},
    )
    validated = ContractValidator().validate(request, contract)

    units = build_hk_basic_units(validated, contract, dao=None, settings=None, session=None)

    assert len(units) == 1
    assert units[0].trade_date is None
    assert units[0].request_params == {"list_status": "L,P"}
    assert units[0].pagination_policy == "offset_limit"
    assert units[0].page_limit == 6000


def test_build_us_basic_units_supports_filters_and_paging() -> None:
    contract = get_sync_v2_contract("us_basic")
    request = RunRequest(
        request_id="req-us-basic",
        dataset_key="us_basic",
        run_profile="point_incremental",
        trigger_source="test",
        params={"classify": ["ADR", "EQ"], "ts_code": "aapl"},
    )
    validated = ContractValidator().validate(request, contract)

    units = build_us_basic_units(validated, contract, dao=None, settings=None, session=None)

    assert len(units) == 1
    assert units[0].trade_date is None
    assert units[0].request_params == {"classify": "ADR,EQT", "ts_code": "AAPL"}
    assert units[0].pagination_policy == "offset_limit"
    assert units[0].page_limit == 6000


def test_hk_us_basic_row_transform_keeps_source_tushare() -> None:
    hk_contract = get_sync_v2_contract("hk_basic")
    us_contract = get_sync_v2_contract("us_basic")

    hk_transform = hk_contract.normalization_spec.row_transform
    us_transform = us_contract.normalization_spec.row_transform

    assert hk_transform is not None
    assert us_transform is not None
    assert hk_transform({"ts_code": "00005.HK"})["source"] == "tushare"
    assert us_transform({"ts_code": "AAPL"})["source"] == "tushare"
