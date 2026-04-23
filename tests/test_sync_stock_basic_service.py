from __future__ import annotations

from src.foundation.services.sync_v2.contracts import FetchResult, RunRequest
from src.foundation.services.sync_v2.dataset_strategies.stock_basic import build_stock_basic_units
from src.foundation.services.sync_v2.normalizer import SyncV2Normalizer
from src.foundation.services.sync_v2.registry import get_sync_v2_contract
from src.foundation.services.sync_v2.validator import ContractValidator


def test_stock_basic_tushare_default_builds_single_unit_with_all_statuses() -> None:
    contract = get_sync_v2_contract("stock_basic")
    request = RunRequest(
        request_id="req-stock-basic-tushare-default",
        dataset_key="stock_basic",
        run_profile="snapshot_refresh",
        trigger_source="test",
        params={},
        source_key="tushare",
    )
    validated = ContractValidator().validate(request, contract)
    units = build_stock_basic_units(validated, contract, dao=None, settings=None, session=None)

    assert len(units) == 1
    assert units[0].request_params["list_status"] == "L,D,P,G"
    assert all(unit.source_key == "tushare" for unit in units)
    assert all(unit.pagination_policy == "offset_limit" for unit in units)
    assert all(unit.page_limit == 6000 for unit in units)


def test_stock_basic_biying_builds_single_snapshot_unit() -> None:
    contract = get_sync_v2_contract("stock_basic")
    request = RunRequest(
        request_id="req-stock-basic-biying",
        dataset_key="stock_basic",
        run_profile="snapshot_refresh",
        trigger_source="test",
        params={},
        source_key="biying",
    )
    validated = ContractValidator().validate(request, contract)
    units = build_stock_basic_units(validated, contract, dao=None, settings=None, session=None)

    assert len(units) == 1
    assert units[0].source_key == "biying"
    assert units[0].request_params == {}
    assert units[0].pagination_policy == "none"
    assert units[0].page_limit is None


def test_stock_basic_all_builds_tushare_plus_biying_units() -> None:
    contract = get_sync_v2_contract("stock_basic")
    request = RunRequest(
        request_id="req-stock-basic-all",
        dataset_key="stock_basic",
        run_profile="snapshot_refresh",
        trigger_source="test",
        params={},
        source_key="all",
    )
    validated = ContractValidator().validate(request, contract)
    units = build_stock_basic_units(validated, contract, dao=None, settings=None, session=None)

    assert len(units) == 2
    assert sum(1 for unit in units if unit.source_key == "tushare") == 1
    assert sum(1 for unit in units if unit.source_key == "biying") == 1
    assert all(unit.requested_source_key == "all" for unit in units)


def test_stock_basic_normalizer_normalizes_ts_code_and_dm() -> None:
    contract = get_sync_v2_contract("stock_basic")
    batch = SyncV2Normalizer().normalize(
        contract=contract,
        fetch_result=FetchResult(
            unit_id="u-stock-basic",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {"ts_code": "000001.sz", "symbol": "000001", "name": "平安银行"},
                {"dm": "000002.sh", "mc": "万科A", "jys": "SH"},
            ],
        ),
    )

    assert batch.rows_rejected == 0
    assert batch.rows_normalized[0]["ts_code"] == "000001.SZ"
    assert batch.rows_normalized[1]["dm"] == "000002.SH"
