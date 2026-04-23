from __future__ import annotations

from datetime import date

from src.foundation.services.sync_v2.contracts import FetchResult, RunRequest
from src.foundation.services.sync_v2.dataset_strategies.stk_holdernumber import build_stk_holdernumber_units
from src.foundation.services.sync_v2.normalizer import SyncV2Normalizer
from src.foundation.services.sync_v2.registry import get_sync_v2_contract
from src.foundation.services.sync_v2.validator import ContractValidator
from src.foundation.services.transform.holdernumber_hash import build_holdernumber_event_key_hash, build_holdernumber_row_key_hash


def test_stk_holdernumber_range_rebuild_expands_natural_dates() -> None:
    contract = get_sync_v2_contract("stk_holdernumber")
    request = RunRequest(
        request_id="req-holdernumber-range",
        dataset_key="stk_holdernumber",
        run_profile="range_rebuild",
        trigger_source="test",
        start_date=date(2026, 3, 21),
        end_date=date(2026, 3, 23),
        params={"ts_code": "000001.SZ"},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_stk_holdernumber_units(validated, contract, dao=None, settings=None, session=None)

    assert [unit.request_params for unit in units] == [
        {"ann_date": "20260321", "ts_code": "000001.SZ"},
        {"ann_date": "20260322", "ts_code": "000001.SZ"},
        {"ann_date": "20260323", "ts_code": "000001.SZ"},
    ]
    assert all(unit.pagination_policy == "offset_limit" for unit in units)
    assert all(unit.page_limit == 3000 for unit in units)


def test_stk_holdernumber_snapshot_refresh_builds_single_unit() -> None:
    contract = get_sync_v2_contract("stk_holdernumber")
    request = RunRequest(
        request_id="req-holdernumber-snapshot",
        dataset_key="stk_holdernumber",
        run_profile="snapshot_refresh",
        trigger_source="test",
        params={"ts_code": "000001.SZ"},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_stk_holdernumber_units(validated, contract, dao=None, settings=None, session=None)

    assert len(units) == 1
    assert units[0].request_params == {"ts_code": "000001.SZ"}


def test_stk_holdernumber_normalizer_generates_hashes() -> None:
    contract = get_sync_v2_contract("stk_holdernumber")
    batch = SyncV2Normalizer().normalize(
        contract=contract,
        fetch_result=FetchResult(
            unit_id="u-holdernumber",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {"ts_code": "000001.SZ", "ann_date": None, "end_date": "19961231", "holder_num": 330500}
            ],
        ),
    )

    assert batch.rows_rejected == 0
    row = batch.rows_normalized[0]
    assert row["end_date"] == date(1996, 12, 31)
    assert row["ann_date"] is None
    assert row["row_key_hash"] == build_holdernumber_row_key_hash(row)
    assert row["event_key_hash"] == build_holdernumber_event_key_hash(row)


def test_stk_holdernumber_normalizer_rejects_missing_business_keys() -> None:
    contract = get_sync_v2_contract("stk_holdernumber")
    batch = SyncV2Normalizer().normalize(
        contract=contract,
        fetch_result=FetchResult(
            unit_id="u-holdernumber-invalid",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {"ts_code": "000001.SZ", "ann_date": None, "end_date": None, "holder_num": 330500}
            ],
        ),
    )

    assert batch.rows_normalized == []
    assert batch.rows_rejected == 1
    assert batch.rejected_reasons == {"ValueError": 1}
