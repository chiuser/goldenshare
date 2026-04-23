from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from src.foundation.services.sync_v2.contracts import FetchResult, RunRequest
from src.foundation.services.sync_v2.dataset_strategies.stock_st import build_stock_st_units
from src.foundation.services.sync_v2.errors import SyncV2ValidationError
from src.foundation.services.sync_v2.normalizer import SyncV2Normalizer
from src.foundation.services.sync_v2.registry import get_sync_v2_contract
from src.foundation.services.sync_v2.validator import ContractValidator


def _fake_dao(open_dates: list[date]) -> SimpleNamespace:
    return SimpleNamespace(
        trade_calendar=SimpleNamespace(get_open_dates=lambda exchange, start, end: open_dates)
    )


def test_stock_st_point_incremental_requires_trade_date() -> None:
    contract = get_sync_v2_contract("stock_st")
    request = RunRequest(
        request_id="req-stock-st-missing-trade-date",
        dataset_key="stock_st",
        run_profile="point_incremental",
        trigger_source="test",
        params={},
    )

    with pytest.raises(SyncV2ValidationError) as exc_info:
        ContractValidator().validate(request, contract)
    assert exc_info.value.structured_error.error_code == "missing_anchor_fields"


def test_stock_st_point_incremental_builds_single_unit() -> None:
    contract = get_sync_v2_contract("stock_st")
    request = RunRequest(
        request_id="req-stock-st-point",
        dataset_key="stock_st",
        run_profile="point_incremental",
        trigger_source="test",
        trade_date=date(2026, 4, 16),
        params={"ts_code": "000001.sz"},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_stock_st_units(validated, contract, dao=_fake_dao([]), settings=SimpleNamespace(default_exchange="SSE"), session=None)

    assert len(units) == 1
    assert units[0].trade_date == date(2026, 4, 16)
    assert units[0].request_params == {"trade_date": "20260416", "ts_code": "000001.SZ"}
    assert units[0].pagination_policy == "offset_limit"
    assert units[0].page_limit == 1000


def test_stock_st_range_rebuild_fans_out_by_trade_calendar() -> None:
    contract = get_sync_v2_contract("stock_st")
    request = RunRequest(
        request_id="req-stock-st-range",
        dataset_key="stock_st",
        run_profile="range_rebuild",
        trigger_source="test",
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 2),
        params={},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_stock_st_units(
        validated,
        contract,
        dao=_fake_dao([date(2026, 4, 1), date(2026, 4, 2)]),
        settings=SimpleNamespace(default_exchange="SSE"),
        session=None,
    )

    assert len(units) == 2
    assert units[0].request_params["trade_date"] == "20260401"
    assert units[1].request_params["trade_date"] == "20260402"


def test_stock_st_normalizer_coerces_trade_date() -> None:
    contract = get_sync_v2_contract("stock_st")
    batch = SyncV2Normalizer().normalize(
        contract=contract,
        fetch_result=FetchResult(
            unit_id="u-stock-st",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "ts_code": "000001.SZ",
                    "name": "平安银行",
                    "trade_date": "20260416",
                    "type": "ST",
                    "type_name": "特别处理",
                }
            ],
        ),
    )
    row = batch.rows_normalized[0]
    assert row["trade_date"] == date(2026, 4, 16)
    assert row["type"] == "ST"
