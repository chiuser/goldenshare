from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from src.foundation.services.sync_v2.contracts import RunRequest
from src.foundation.services.sync_v2.errors import SyncV2ValidationError
from src.foundation.services.sync_v2.registry import get_sync_v2_contract
from src.foundation.services.sync_v2.validator import ContractValidator


def test_validator_accepts_point_incremental_trade_date() -> None:
    validator = ContractValidator()
    contract = get_sync_v2_contract("stk_limit")
    request = RunRequest(
        request_id="req-1",
        dataset_key="stk_limit",
        run_profile="point_incremental",
        trigger_source="manual",
        params={"trade_date": "20260418", "ts_code": "000001.SZ"},
    )

    validated = validator.validate(request=request, contract=contract, strict=True)

    assert validated.trade_date == date(2026, 4, 18)
    assert validated.params["trade_date"] == date(2026, 4, 18)
    assert validated.params["ts_code"] == "000001.SZ"


def test_validator_rejects_unknown_params_when_strict() -> None:
    validator = ContractValidator()
    contract = get_sync_v2_contract("stk_limit")
    request = RunRequest(
        request_id="req-2",
        dataset_key="stk_limit",
        run_profile="point_incremental",
        trigger_source="manual",
        params={"trade_date": "20260418", "unknown": "x"},
    )

    with pytest.raises(SyncV2ValidationError) as exc_info:
        validator.validate(request=request, contract=contract, strict=True)

    assert exc_info.value.structured_error.error_code == "unknown_params"


def test_validator_rejects_invalid_range() -> None:
    validator = ContractValidator()
    contract = get_sync_v2_contract("margin")
    request = RunRequest(
        request_id="req-3",
        dataset_key="margin",
        run_profile="range_rebuild",
        trigger_source="manual",
        params={"start_date": "20260420", "end_date": "20260418"},
    )

    with pytest.raises(SyncV2ValidationError) as exc_info:
        validator.validate(request=request, contract=contract, strict=True)

    assert exc_info.value.structured_error.error_code == "invalid_range"


def test_validator_rejects_snapshot_refresh_with_time_anchor() -> None:
    validator = ContractValidator()
    contract = get_sync_v2_contract("trade_cal")
    request = RunRequest(
        request_id="req-4",
        dataset_key="trade_cal",
        run_profile="snapshot_refresh",
        trigger_source="manual",
        params={"trade_date": "20260418"},
    )

    with pytest.raises(SyncV2ValidationError) as exc_info:
        validator.validate(request=request, contract=contract, strict=True)

    assert exc_info.value.structured_error.error_code == "time_anchor_not_allowed"


def test_validator_accepts_daily_basic_range_rebuild() -> None:
    validator = ContractValidator()
    contract = get_sync_v2_contract("daily_basic")
    request = RunRequest(
        request_id="req-5",
        dataset_key="daily_basic",
        run_profile="range_rebuild",
        trigger_source="manual",
        params={"start_date": "20260418", "end_date": "20260421", "ts_code": "000001.SZ"},
    )

    validated = validator.validate(request=request, contract=contract, strict=True)

    assert validated.start_date == date(2026, 4, 18)
    assert validated.end_date == date(2026, 4, 21)
    assert validated.params["ts_code"] == "000001.SZ"


def test_validator_accepts_suspend_d_incremental_with_suspend_type() -> None:
    validator = ContractValidator()
    contract = get_sync_v2_contract("suspend_d")
    request = RunRequest(
        request_id="req-6",
        dataset_key="suspend_d",
        run_profile="point_incremental",
        trigger_source="manual",
        params={"trade_date": "20260421", "suspend_type": "S"},
    )

    validated = validator.validate(request=request, contract=contract, strict=True)

    assert validated.trade_date == date(2026, 4, 21)
    assert validated.params["suspend_type"] == "S"


def test_validator_accepts_cyq_perf_incremental_with_ts_code() -> None:
    validator = ContractValidator()
    contract = get_sync_v2_contract("cyq_perf")
    request = RunRequest(
        request_id="req-7",
        dataset_key="cyq_perf",
        run_profile="point_incremental",
        trigger_source="manual",
        params={"trade_date": "20260421", "ts_code": "000001.SZ"},
    )

    validated = validator.validate(request=request, contract=contract, strict=True)

    assert validated.trade_date == date(2026, 4, 21)
    assert validated.params["ts_code"] == "000001.SZ"


def test_validator_accepts_moneyflow_ths_range_rebuild() -> None:
    validator = ContractValidator()
    contract = get_sync_v2_contract("moneyflow_ths")
    request = RunRequest(
        request_id="req-8",
        dataset_key="moneyflow_ths",
        run_profile="range_rebuild",
        trigger_source="manual",
        params={"start_date": "20260418", "end_date": "20260421", "ts_code": "000001.SZ"},
    )

    validated = validator.validate(request=request, contract=contract, strict=True)

    assert validated.start_date == date(2026, 4, 18)
    assert validated.end_date == date(2026, 4, 21)
    assert validated.params["ts_code"] == "000001.SZ"


def test_validator_accepts_moneyflow_mkt_dc_incremental() -> None:
    validator = ContractValidator()
    contract = get_sync_v2_contract("moneyflow_mkt_dc")
    request = RunRequest(
        request_id="req-9",
        dataset_key="moneyflow_mkt_dc",
        run_profile="point_incremental",
        trigger_source="manual",
        params={"trade_date": "20260421"},
    )

    validated = validator.validate(request=request, contract=contract, strict=True)

    assert validated.trade_date == date(2026, 4, 21)


def test_validator_accepts_moneyflow_range_rebuild() -> None:
    validator = ContractValidator()
    contract = get_sync_v2_contract("moneyflow")
    request = RunRequest(
        request_id="req-10",
        dataset_key="moneyflow",
        run_profile="range_rebuild",
        trigger_source="manual",
        params={"start_date": "20260415", "end_date": "20260417", "ts_code": "000001.SZ"},
    )

    validated = validator.validate(request=request, contract=contract, strict=True)

    assert validated.start_date == date(2026, 4, 15)
    assert validated.end_date == date(2026, 4, 17)
    assert validated.params["ts_code"] == "000001.SZ"


def test_validator_accepts_limit_step_incremental_with_nums() -> None:
    validator = ContractValidator()
    contract = get_sync_v2_contract("limit_step")
    request = RunRequest(
        request_id="req-11",
        dataset_key="limit_step",
        run_profile="point_incremental",
        trigger_source="manual",
        params={"trade_date": "20260421", "nums": "2"},
    )

    validated = validator.validate(request=request, contract=contract, strict=True)

    assert validated.trade_date == date(2026, 4, 21)
    assert validated.params["nums"] == "2"


def test_validator_accepts_limit_cpt_list_range_rebuild() -> None:
    validator = ContractValidator()
    contract = get_sync_v2_contract("limit_cpt_list")
    request = RunRequest(
        request_id="req-12",
        dataset_key="limit_cpt_list",
        run_profile="range_rebuild",
        trigger_source="manual",
        params={"start_date": "20260418", "end_date": "20260421", "ts_code": "000001.SZ"},
    )

    validated = validator.validate(request=request, contract=contract, strict=True)

    assert validated.start_date == date(2026, 4, 18)
    assert validated.end_date == date(2026, 4, 21)
    assert validated.params["ts_code"] == "000001.SZ"


def test_validator_accepts_top_list_incremental_with_ts_code() -> None:
    validator = ContractValidator()
    contract = get_sync_v2_contract("top_list")
    request = RunRequest(
        request_id="req-13",
        dataset_key="top_list",
        run_profile="point_incremental",
        trigger_source="manual",
        params={"trade_date": "20260421", "ts_code": "000001.SZ"},
    )

    validated = validator.validate(request=request, contract=contract, strict=True)

    assert validated.trade_date == date(2026, 4, 21)
    assert validated.params["ts_code"] == "000001.SZ"


def test_validator_accepts_block_trade_range_rebuild() -> None:
    validator = ContractValidator()
    contract = get_sync_v2_contract("block_trade")
    request = RunRequest(
        request_id="req-14",
        dataset_key="block_trade",
        run_profile="range_rebuild",
        trigger_source="manual",
        params={"start_date": "20260418", "end_date": "20260421"},
    )

    validated = validator.validate(request=request, contract=contract, strict=True)

    assert validated.start_date == date(2026, 4, 18)
    assert validated.end_date == date(2026, 4, 21)


def test_validator_accepts_stock_st_incremental() -> None:
    validator = ContractValidator()
    contract = get_sync_v2_contract("stock_st")
    request = RunRequest(
        request_id="req-15",
        dataset_key="stock_st",
        run_profile="point_incremental",
        trigger_source="manual",
        params={"trade_date": "20260421"},
    )

    validated = validator.validate(request=request, contract=contract, strict=True)

    assert validated.trade_date == date(2026, 4, 21)


def test_validator_accepts_stk_nineturn_range_with_ts_code() -> None:
    validator = ContractValidator()
    contract = get_sync_v2_contract("stk_nineturn")
    request = RunRequest(
        request_id="req-16",
        dataset_key="stk_nineturn",
        run_profile="range_rebuild",
        trigger_source="manual",
        params={"start_date": "20260418", "end_date": "20260421", "ts_code": "000001.SZ"},
    )

    validated = validator.validate(request=request, contract=contract, strict=True)

    assert validated.start_date == date(2026, 4, 18)
    assert validated.end_date == date(2026, 4, 21)
    assert validated.params["ts_code"] == "000001.SZ"


def test_validator_accepts_dc_member_range_with_idx_type() -> None:
    validator = ContractValidator()
    contract = get_sync_v2_contract("dc_member")
    request = RunRequest(
        request_id="req-17",
        dataset_key="dc_member",
        run_profile="range_rebuild",
        trigger_source="manual",
        params={"start_date": "20260418", "end_date": "20260421", "idx_type": "概念板块"},
    )

    validated = validator.validate(request=request, contract=contract, strict=True)

    assert validated.start_date == date(2026, 4, 18)
    assert validated.end_date == date(2026, 4, 21)
    assert validated.params["idx_type"] == "概念板块"


def test_validator_accepts_index_basic_point_incremental_with_external_trade_date() -> None:
    validator = ContractValidator()
    contract = get_sync_v2_contract("index_basic")
    request = RunRequest(
        request_id="req-18",
        dataset_key="index_basic",
        run_profile="point_incremental",
        trigger_source="manual",
        params={"ts_code": "000001.SH"},
        trade_date=date(2026, 4, 21),
    )

    validated = validator.validate(request=request, contract=contract, strict=True)

    assert validated.trade_date == date(2026, 4, 21)
    assert validated.params["ts_code"] == "000001.SH"


def test_validator_accepts_ths_member_snapshot_refresh() -> None:
    validator = ContractValidator()
    contract = get_sync_v2_contract("ths_member")
    request = RunRequest(
        request_id="req-ths-member-snapshot",
        dataset_key="ths_member",
        run_profile="snapshot_refresh",
        trigger_source="manual",
        params={},
    )

    validated = validator.validate(request=request, contract=contract, strict=True)

    assert validated.trade_date is None
    assert validated.start_date is None
    assert validated.end_date is None


def test_validator_accepts_dc_hot_range_rebuild_with_filters() -> None:
    validator = ContractValidator()
    contract = get_sync_v2_contract("dc_hot")
    request = RunRequest(
        request_id="req-dc-hot-range",
        dataset_key="dc_hot",
        run_profile="range_rebuild",
        trigger_source="manual",
        params={
            "start_date": "20260415",
            "end_date": "20260417",
            "market": "A股市场",
            "hot_type": "概念",
            "is_new": "Y",
        },
    )

    validated = validator.validate(request=request, contract=contract, strict=True)

    assert validated.start_date == date(2026, 4, 15)
    assert validated.end_date == date(2026, 4, 17)
    assert validated.params["market"] == "A股市场"
    assert validated.params["hot_type"] == "概念"
    assert validated.params["is_new"] == "Y"


def test_validator_accepts_dividend_range_rebuild_with_event_filters() -> None:
    validator = ContractValidator()
    contract = get_sync_v2_contract("dividend")
    request = RunRequest(
        request_id="req-dividend-range",
        dataset_key="dividend",
        run_profile="range_rebuild",
        trigger_source="manual",
        params={
            "start_date": "20260401",
            "end_date": "20260403",
            "ts_code": "000001.SZ",
            "record_date": "20260402",
        },
    )

    validated = validator.validate(request=request, contract=contract, strict=True)

    assert validated.start_date == date(2026, 4, 1)
    assert validated.end_date == date(2026, 4, 3)
    assert validated.params["ts_code"] == "000001.SZ"
    assert validated.params["record_date"] == date(2026, 4, 2)


def test_validator_accepts_holdernumber_range_rebuild_with_enddate() -> None:
    validator = ContractValidator()
    contract = get_sync_v2_contract("stk_holdernumber")
    request = RunRequest(
        request_id="req-holdernumber-range",
        dataset_key="stk_holdernumber",
        run_profile="range_rebuild",
        trigger_source="manual",
        params={
            "start_date": "20260401",
            "end_date": "20260402",
            "enddate": "20260331",
        },
    )

    validated = validator.validate(request=request, contract=contract, strict=True)

    assert validated.start_date == date(2026, 4, 1)
    assert validated.end_date == date(2026, 4, 2)
    assert validated.params["enddate"] == date(2026, 3, 31)


def test_validator_accepts_index_weight_range_rebuild() -> None:
    validator = ContractValidator()
    contract = get_sync_v2_contract("index_weight")
    request = RunRequest(
        request_id="req-index-weight-range",
        dataset_key="index_weight",
        run_profile="range_rebuild",
        trigger_source="manual",
        params={
            "index_code": "000300.SH",
            "start_date": "20260401",
            "end_date": "20260430",
        },
    )

    validated = validator.validate(request=request, contract=contract, strict=True)

    assert validated.start_date == date(2026, 4, 1)
    assert validated.end_date == date(2026, 4, 30)
    assert validated.params["index_code"] == "000300.SH"


def test_validator_accepts_hk_basic_snapshot_refresh_with_list_status() -> None:
    validator = ContractValidator()
    contract = get_sync_v2_contract("hk_basic")
    request = RunRequest(
        request_id="req-19",
        dataset_key="hk_basic",
        run_profile="snapshot_refresh",
        trigger_source="manual",
        params={"list_status": "L,D"},
    )

    validated = validator.validate(request=request, contract=contract, strict=True)

    assert validated.trade_date is None
    assert validated.start_date is None
    assert validated.end_date is None
    assert validated.params["list_status"] == ["L", "D"]


def test_validator_accepts_broker_recommend_point_incremental_with_month_key() -> None:
    validator = ContractValidator()
    contract = get_sync_v2_contract("broker_recommend")
    request = RunRequest(
        request_id="req-20",
        dataset_key="broker_recommend",
        run_profile="point_incremental",
        trigger_source="manual",
        params={"month": "2026-04"},
    )

    validated = validator.validate(request=request, contract=contract, strict=True)

    assert validated.trade_date is None
    assert validated.params["month"] == "202604"


def test_validator_rejects_point_incremental_when_window_policy_is_none() -> None:
    validator = ContractValidator()
    contract = get_sync_v2_contract("stk_limit")
    broken_contract = replace(
        contract,
        planning_spec=replace(contract.planning_spec, window_policy="none"),
    )
    request = RunRequest(
        request_id="req-21",
        dataset_key="stk_limit",
        run_profile="point_incremental",
        trigger_source="manual",
        params={"trade_date": "20260421"},
    )

    with pytest.raises(SyncV2ValidationError) as exc_info:
        validator.validate(request=request, contract=broken_contract, strict=True)

    assert exc_info.value.structured_error.error_code == "invalid_window_for_profile"
