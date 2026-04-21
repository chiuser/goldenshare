from __future__ import annotations

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
