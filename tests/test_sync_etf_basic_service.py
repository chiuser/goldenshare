from __future__ import annotations

from decimal import Decimal

from src.foundation.services.sync_v2.contracts import FetchResult, RunRequest
from src.foundation.services.sync_v2.dataset_strategies.common import build_default_units
from src.foundation.services.sync_v2.normalizer import SyncV2Normalizer
from src.foundation.services.sync_v2.registry import get_sync_v2_contract
from src.foundation.services.sync_v2.validator import ContractValidator


def test_etf_basic_v2_units_and_normalization() -> None:
    contract = get_sync_v2_contract("etf_basic")
    request = RunRequest(
        request_id="req-etf-basic",
        dataset_key="etf_basic",
        run_profile="snapshot_refresh",
        trigger_source="test",
        params={"list_status": ["L", "D"], "exchange": "SSE"},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_default_units(validated, contract, dao=None, settings=None, session=None, page_limit=6000)

    assert len(units) == 1
    assert units[0].trade_date is None
    assert units[0].request_params["list_status"] == "L,D"
    assert units[0].request_params["exchange"] == "SSE"
    assert units[0].pagination_policy == "offset_limit"
    assert units[0].page_limit == 6000

    fetch_result = FetchResult(
        unit_id="u-etf-basic",
        request_count=1,
        retry_count=0,
        latency_ms=1,
        rows_raw=[
            {
                "ts_code": "510300.SH",
                "csname": "沪深300ETF",
                "extname": "沪深300交易型开放式指数证券投资基金",
                "cname": "300ETF",
                "index_code": "000300.SH",
                "index_name": "沪深300",
                "setup_date": "2012-05-04",
                "list_date": "2012-05-28",
                "list_status": "L",
                "exchange": "SSE",
                "mgr_name": "华泰柏瑞基金",
                "custod_name": "中国工商银行",
                "mgt_fee": "0.500000",
                "etf_type": "股票型",
            }
        ],
    )
    batch = SyncV2Normalizer().normalize(contract=contract, fetch_result=fetch_result)
    row = batch.rows_normalized[0]

    assert len(batch.rows_normalized) == 1
    assert row["setup_date"].isoformat() == "2012-05-04"
    assert row["list_date"].isoformat() == "2012-05-28"
    assert row["mgt_fee"] == Decimal("0.500000")
