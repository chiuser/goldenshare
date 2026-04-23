from __future__ import annotations

from datetime import date

import pytest

from src.foundation.services.sync_v2.contracts import RunRequest
from src.foundation.services.sync_v2.dataset_strategies.fund_daily import build_fund_daily_units
from src.foundation.services.sync_v2.errors import SyncV2ValidationError
from src.foundation.services.sync_v2.registry import get_sync_v2_contract
from src.foundation.services.sync_v2.validator import ContractValidator


def test_build_fund_daily_units_point_incremental_includes_trade_date_and_ts_code() -> None:
    contract = get_sync_v2_contract("fund_daily")
    request = RunRequest(
        request_id="req-fund-daily",
        dataset_key="fund_daily",
        run_profile="point_incremental",
        trigger_source="test",
        trade_date=date(2026, 3, 31),
        params={"ts_code": "510300.SH"},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_fund_daily_units(validated, contract, dao=None, settings=None, session=None)

    assert len(units) == 1
    assert units[0].trade_date == date(2026, 3, 31)
    assert units[0].request_params == {"trade_date": "20260331", "ts_code": "510300.SH"}
    assert units[0].pagination_policy == "offset_limit"
    assert units[0].page_limit == 5000


def test_fund_daily_validator_rejects_missing_trade_date_for_point_incremental() -> None:
    contract = get_sync_v2_contract("fund_daily")
    request = RunRequest(
        request_id="req-fund-daily-missing-trade-date",
        dataset_key="fund_daily",
        run_profile="point_incremental",
        trigger_source="test",
        params={},
    )

    with pytest.raises(SyncV2ValidationError) as exc_info:
        ContractValidator().validate(request, contract)
    exc = exc_info.value
    assert exc.structured_error.error_code == "missing_anchor_fields"
