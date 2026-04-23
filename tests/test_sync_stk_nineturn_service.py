from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.foundation.services.sync_v2.contracts import FetchResult, RunRequest
from src.foundation.services.sync_v2.dataset_strategies.stk_nineturn import build_stk_nineturn_units
from src.foundation.services.sync_v2.errors import SyncV2ValidationError
from src.foundation.services.sync_v2.normalizer import SyncV2Normalizer
from src.foundation.services.sync_v2.registry import get_sync_v2_contract
from src.foundation.services.sync_v2.validator import ContractValidator


def _fake_dao(open_dates: list[date]) -> SimpleNamespace:
    return SimpleNamespace(
        trade_calendar=SimpleNamespace(get_open_dates=lambda exchange, start, end: open_dates)
    )


def test_stk_nineturn_point_incremental_requires_trade_date() -> None:
    contract = get_sync_v2_contract("stk_nineturn")
    request = RunRequest(
        request_id="req-stk-nineturn-missing-trade-date",
        dataset_key="stk_nineturn",
        run_profile="point_incremental",
        trigger_source="test",
        params={},
    )

    with pytest.raises(SyncV2ValidationError) as exc_info:
        ContractValidator().validate(request, contract)
    assert exc_info.value.structured_error.error_code == "missing_anchor_fields"


def test_stk_nineturn_point_incremental_builds_unit_with_daily_freq() -> None:
    contract = get_sync_v2_contract("stk_nineturn")
    request = RunRequest(
        request_id="req-stk-nineturn-point",
        dataset_key="stk_nineturn",
        run_profile="point_incremental",
        trigger_source="test",
        trade_date=date(2026, 4, 10),
        params={"ts_code": "000001.sz"},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_stk_nineturn_units(validated, contract, dao=_fake_dao([]), settings=SimpleNamespace(default_exchange="SSE"), session=None)

    assert len(units) == 1
    assert units[0].request_params == {"trade_date": "20260410", "freq": "daily", "ts_code": "000001.SZ"}
    assert units[0].pagination_policy == "offset_limit"
    assert units[0].page_limit == 10000


def test_stk_nineturn_range_rebuild_fans_out_by_trade_calendar() -> None:
    contract = get_sync_v2_contract("stk_nineturn")
    request = RunRequest(
        request_id="req-stk-nineturn-range",
        dataset_key="stk_nineturn",
        run_profile="range_rebuild",
        trigger_source="test",
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 2),
        params={},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_stk_nineturn_units(
        validated,
        contract,
        dao=_fake_dao([date(2026, 4, 1), date(2026, 4, 2)]),
        settings=SimpleNamespace(default_exchange="SSE"),
        session=None,
    )

    assert len(units) == 2
    assert units[0].request_params["trade_date"] == "20260401"
    assert units[1].request_params["trade_date"] == "20260402"
    assert units[0].request_params["freq"] == "daily"


def test_stk_nineturn_normalizer_coerces_numeric_fields() -> None:
    contract = get_sync_v2_contract("stk_nineturn")
    batch = SyncV2Normalizer().normalize(
        contract=contract,
        fetch_result=FetchResult(
            unit_id="u-stk-nineturn",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260410",
                    "freq": "daily",
                    "open": "10.11",
                    "high": "10.22",
                    "low": "9.98",
                    "close": "10.05",
                    "vol": "123456.0000",
                    "amount": "987654.0000",
                    "up_count": "3",
                    "down_count": "0",
                    "nine_up_turn": "Y",
                    "nine_down_turn": "N",
                }
            ],
        ),
    )
    row = batch.rows_normalized[0]
    assert row["trade_date"] == date(2026, 4, 10)
    assert row["open"] == Decimal("10.11")
    assert row["up_count"] == Decimal("3")
