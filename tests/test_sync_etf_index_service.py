from __future__ import annotations

from decimal import Decimal

from src.foundation.services.sync_v2.contracts import FetchResult, RunRequest
from src.foundation.services.sync_v2.dataset_strategies.common import build_default_units
from src.foundation.services.sync_v2.normalizer import SyncV2Normalizer
from src.foundation.services.sync_v2.registry import get_sync_v2_contract
from src.foundation.services.sync_v2.validator import ContractValidator


def test_etf_index_v2_units_and_normalization() -> None:
    contract = get_sync_v2_contract("etf_index")
    request = RunRequest(
        request_id="req-etf-index",
        dataset_key="etf_index",
        run_profile="snapshot_refresh",
        trigger_source="test",
        params={"ts_code": "csi931151.csi", "pub_date": "2025-01-31", "base_date": "2025-01-02"},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_default_units(validated, contract, dao=None, settings=None, session=None, page_limit=6000)

    assert len(units) == 1
    assert units[0].trade_date is None
    assert units[0].request_params == {
        "ts_code": "CSI931151.CSI",
        "pub_date": "20250131",
        "base_date": "20250102",
    }
    assert units[0].pagination_policy == "offset_limit"
    assert units[0].page_limit == 6000

    fetch_result = FetchResult(
        unit_id="u-etf-index",
        request_count=1,
        retry_count=0,
        latency_ms=1,
        rows_raw=[
            {
                "ts_code": "CSI931151.CSI",
                "indx_name": "中证光伏产业指数",
                "indx_csname": "光伏产业指数",
                "pub_party_name": "中证指数有限公司",
                "pub_date": "2025-01-31",
                "base_date": "2025-01-02",
                "bp": "1000.000000",
                "adj_circle": "季度",
            }
        ],
    )
    batch = SyncV2Normalizer().normalize(contract=contract, fetch_result=fetch_result)
    row = batch.rows_normalized[0]

    assert len(batch.rows_normalized) == 1
    assert row["pub_date"].isoformat() == "2025-01-31"
    assert row["base_date"].isoformat() == "2025-01-02"
    assert row["bp"] == Decimal("1000.000000")
