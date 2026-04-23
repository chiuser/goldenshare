from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from src.foundation.services.sync_v2.contracts import FetchResult, RunRequest
from src.foundation.services.sync_v2.dataset_strategies.suspend_d import build_suspend_d_units
from src.foundation.services.sync_v2.errors import SyncV2ValidationError
from src.foundation.services.sync_v2.normalizer import SyncV2Normalizer
from src.foundation.services.sync_v2.registry import get_sync_v2_contract
from src.foundation.services.sync_v2.validator import ContractValidator


def _fake_dao(open_dates: list[date]) -> SimpleNamespace:
    return SimpleNamespace(
        trade_calendar=SimpleNamespace(get_open_dates=lambda exchange, start, end: open_dates)
    )


def test_suspend_d_point_incremental_requires_trade_date() -> None:
    contract = get_sync_v2_contract("suspend_d")
    request = RunRequest(
        request_id="req-suspend-d-missing-trade-date",
        dataset_key="suspend_d",
        run_profile="point_incremental",
        trigger_source="test",
        params={},
    )

    with pytest.raises(SyncV2ValidationError) as exc_info:
        ContractValidator().validate(request, contract)
    assert exc_info.value.structured_error.error_code == "missing_anchor_fields"


def test_suspend_d_point_incremental_builds_unit_with_upper_suspend_type() -> None:
    contract = get_sync_v2_contract("suspend_d")
    request = RunRequest(
        request_id="req-suspend-d-point",
        dataset_key="suspend_d",
        run_profile="point_incremental",
        trigger_source="test",
        trade_date=date(2026, 4, 10),
        params={"suspend_type": "s", "ts_code": "000001.sz"},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_suspend_d_units(validated, contract, dao=_fake_dao([]), settings=SimpleNamespace(default_exchange="SSE"), session=None)

    assert len(units) == 1
    assert units[0].request_params == {
        "trade_date": "20260410",
        "ts_code": "000001.SZ",
        "suspend_type": "S",
    }
    assert units[0].pagination_policy == "offset_limit"
    assert units[0].page_limit == 5000


def test_suspend_d_range_rebuild_fans_out_by_trade_calendar() -> None:
    contract = get_sync_v2_contract("suspend_d")
    request = RunRequest(
        request_id="req-suspend-d-range",
        dataset_key="suspend_d",
        run_profile="range_rebuild",
        trigger_source="test",
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 2),
        params={"suspend_type": "R"},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_suspend_d_units(
        validated,
        contract,
        dao=_fake_dao([date(2026, 4, 1), date(2026, 4, 2)]),
        settings=SimpleNamespace(default_exchange="SSE"),
        session=None,
    )

    assert len(units) == 2
    assert units[0].request_params["trade_date"] == "20260401"
    assert units[0].request_params["suspend_type"] == "R"
    assert units[1].request_params["trade_date"] == "20260402"


def test_suspend_d_normalizer_generates_row_key_hash() -> None:
    contract = get_sync_v2_contract("suspend_d")
    batch = SyncV2Normalizer().normalize(
        contract=contract,
        fetch_result=FetchResult(
            unit_id="u-suspend-d",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "trade_date": "20260410",
                    "ts_code": "000001.SZ",
                    "suspend_timing": "09:30-10:30",
                    "suspend_type": "S",
                }
            ],
        ),
    )
    row = batch.rows_normalized[0]
    assert row["trade_date"] == date(2026, 4, 10)
    assert row["row_key_hash"]
    assert len(row["row_key_hash"]) == 64
