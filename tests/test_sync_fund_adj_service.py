from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from src.foundation.services.sync_v2.contracts import FetchResult, RunRequest
from src.foundation.services.sync_v2.dataset_strategies.fund_adj import build_fund_adj_units
from src.foundation.services.sync_v2.normalizer import SyncV2Normalizer
from src.foundation.services.sync_v2.registry import get_sync_v2_contract
from src.foundation.services.sync_v2.validator import ContractValidator


def test_fund_adj_point_incremental_builds_single_trade_date_unit() -> None:
    contract = get_sync_v2_contract("fund_adj")
    request = RunRequest(
        request_id="req-fund-adj-point",
        dataset_key="fund_adj",
        run_profile="point_incremental",
        trigger_source="test",
        trade_date=date(2026, 3, 31),
        params={"ts_code": "510300.SH"},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_fund_adj_units(validated, contract, dao=None, settings=None, session=None)

    assert len(units) == 1
    assert units[0].request_params == {"trade_date": "20260331", "ts_code": "510300.SH"}
    assert units[0].pagination_policy == "offset_limit"
    assert units[0].page_limit == 2000


def test_fund_adj_range_rebuild_uses_start_end_window() -> None:
    contract = get_sync_v2_contract("fund_adj")
    request = RunRequest(
        request_id="req-fund-adj-range",
        dataset_key="fund_adj",
        run_profile="range_rebuild",
        trigger_source="test",
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 31),
        params={"ts_code": "159915.SZ"},
    )
    validated = ContractValidator().validate(request, contract)
    dao = SimpleNamespace(
        trade_calendar=SimpleNamespace(
            get_open_dates=lambda exchange, start_date, end_date: [date(2026, 3, 31)]
        )
    )
    settings = SimpleNamespace(default_exchange="SSE")
    units = build_fund_adj_units(validated, contract, dao=dao, settings=settings, session=None)

    assert len(units) == 1
    assert units[0].request_params == {
        "start_date": "20260301",
        "end_date": "20260331",
        "ts_code": "159915.SZ",
    }


def test_fund_adj_normalizer_coerces_types() -> None:
    contract = get_sync_v2_contract("fund_adj")
    batch = SyncV2Normalizer().normalize(
        contract=contract,
        fetch_result=FetchResult(
            unit_id="u-fund-adj",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "ts_code": "510300.SH",
                    "trade_date": "20260331",
                    "adj_factor": "1.001",
                }
            ],
        ),
    )

    assert batch.rows_rejected == 0
    row = batch.rows_normalized[0]
    assert row["ts_code"] == "510300.SH"
    assert row["trade_date"] == date(2026, 3, 31)
    assert row["adj_factor"] == Decimal("1.001")
