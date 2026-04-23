from __future__ import annotations

from datetime import date

import pytest

from src.foundation.services.sync_v2.contracts import FetchResult, RunRequest
from src.foundation.services.sync_v2.dataset_strategies.stk_factor_pro import build_stk_factor_pro_units
from src.foundation.services.sync_v2.errors import SyncV2ValidationError
from src.foundation.services.sync_v2.normalizer import SyncV2Normalizer
from src.foundation.services.sync_v2.registry import get_sync_v2_contract
from src.foundation.services.sync_v2.validator import ContractValidator


def test_stk_factor_pro_point_incremental_requires_trade_date() -> None:
    contract = get_sync_v2_contract("stk_factor_pro")
    request = RunRequest(
        request_id="req-stk-factor-pro-missing-anchor",
        dataset_key="stk_factor_pro",
        run_profile="point_incremental",
        trigger_source="test",
        params={},
    )

    with pytest.raises(SyncV2ValidationError) as exc_info:
        ContractValidator().validate(request, contract)
    assert exc_info.value.structured_error.error_code == "missing_anchor_fields"


def test_stk_factor_pro_point_incremental_builds_trade_date_unit() -> None:
    contract = get_sync_v2_contract("stk_factor_pro")
    request = RunRequest(
        request_id="req-stk-factor-pro-point",
        dataset_key="stk_factor_pro",
        run_profile="point_incremental",
        trigger_source="test",
        trade_date=date(2026, 4, 10),
        params={"ts_code": "000001.SZ"},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_stk_factor_pro_units(validated, contract, dao=None, settings=None, session=None)

    assert len(units) == 1
    assert units[0].request_params == {"trade_date": "20260410", "ts_code": "000001.SZ"}
    assert units[0].pagination_policy == "offset_limit"
    assert units[0].page_limit == 10000


def test_stk_factor_pro_normalizer_maps_fields() -> None:
    contract = get_sync_v2_contract("stk_factor_pro")
    batch = SyncV2Normalizer().normalize(
        contract=contract,
        fetch_result=FetchResult(
            unit_id="u-stk-factor-pro",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260410",
                    "close": 10.11,
                    "open": 10.01,
                    "macd_bfq": 0.12,
                    "rsi_bfq_6": 56.78,
                }
            ],
        ),
    )

    assert batch.rows_rejected == 0
    row = batch.rows_normalized[0]
    assert row["ts_code"] == "000001.SZ"
    assert row["trade_date"] == date(2026, 4, 10)
    assert row["close"] == 10.11
    assert row["macd_bfq"] == 0.12
