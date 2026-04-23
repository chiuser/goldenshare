from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.foundation.services.sync_v2.contracts import FetchResult, RunRequest
from src.foundation.services.sync_v2.dataset_strategies.block_trade import build_block_trade_units
from src.foundation.services.sync_v2.normalizer import SyncV2Normalizer
from src.foundation.services.sync_v2.registry import get_sync_v2_contract
from src.foundation.services.sync_v2.validator import ContractValidator


def test_block_trade_point_incremental_builds_trade_date_unit() -> None:
    contract = get_sync_v2_contract("block_trade")
    request = RunRequest(
        request_id="req-block-trade-point",
        dataset_key="block_trade",
        run_profile="point_incremental",
        trigger_source="test",
        trade_date=date(2026, 4, 1),
        params={"ts_code": "000001.SZ"},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_block_trade_units(validated, contract, dao=None, settings=None, session=None)

    assert len(units) == 1
    assert units[0].request_params == {"trade_date": "20260401", "ts_code": "000001.SZ"}
    assert units[0].pagination_policy == "offset_limit"
    assert units[0].page_limit == 1000


def test_block_trade_normalizer_keeps_duplicate_rows() -> None:
    contract = get_sync_v2_contract("block_trade")
    batch = SyncV2Normalizer().normalize(
        contract=contract,
        fetch_result=FetchResult(
            unit_id="u-block-trade",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260401",
                    "buyer": "A",
                    "seller": "B",
                    "price": "10.01",
                    "vol": "1000",
                    "amount": "10010",
                },
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260401",
                    "buyer": "A",
                    "seller": "B",
                    "price": "10.01",
                    "vol": "1000",
                    "amount": "10010",
                },
            ],
        ),
    )

    assert batch.rows_rejected == 0
    assert len(batch.rows_normalized) == 2
    first = batch.rows_normalized[0]
    second = batch.rows_normalized[1]
    assert first == second
    assert first["trade_date"] == date(2026, 4, 1)
    assert first["price"] == Decimal("10.01")
