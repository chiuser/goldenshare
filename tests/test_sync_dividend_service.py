from __future__ import annotations

from datetime import date

from src.foundation.services.sync_v2.contracts import FetchResult, RunRequest
from src.foundation.services.sync_v2.dataset_strategies.dividend import build_dividend_units
from src.foundation.services.sync_v2.normalizer import SyncV2Normalizer
from src.foundation.services.sync_v2.registry import get_sync_v2_contract
from src.foundation.services.sync_v2.validator import ContractValidator
from src.foundation.services.transform.dividend_hash import build_dividend_event_key_hash, build_dividend_row_key_hash


def test_dividend_range_rebuild_expands_natural_dates() -> None:
    contract = get_sync_v2_contract("dividend")
    request = RunRequest(
        request_id="req-dividend-range",
        dataset_key="dividend",
        run_profile="range_rebuild",
        trigger_source="test",
        start_date=date(2026, 3, 21),
        end_date=date(2026, 3, 23),
        params={"ts_code": "000001.SZ"},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_dividend_units(validated, contract, dao=None, settings=None, session=None)

    assert [unit.request_params for unit in units] == [
        {"ann_date": "20260321", "ts_code": "000001.SZ"},
        {"ann_date": "20260322", "ts_code": "000001.SZ"},
        {"ann_date": "20260323", "ts_code": "000001.SZ"},
    ]
    assert all(unit.pagination_policy == "offset_limit" for unit in units)
    assert all(unit.page_limit == 6000 for unit in units)


def test_dividend_snapshot_refresh_without_anchor_builds_single_unit() -> None:
    contract = get_sync_v2_contract("dividend")
    request = RunRequest(
        request_id="req-dividend-snapshot",
        dataset_key="dividend",
        run_profile="snapshot_refresh",
        trigger_source="test",
        params={"ts_code": "000001.SZ"},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_dividend_units(validated, contract, dao=None, settings=None, session=None)

    assert len(units) == 1
    assert units[0].request_params == {"ts_code": "000001.SZ"}


def test_dividend_normalizer_autofills_ex_date_and_generates_hashes() -> None:
    contract = get_sync_v2_contract("dividend")
    batch = SyncV2Normalizer().normalize(
        contract=contract,
        fetch_result=FetchResult(
            unit_id="u-dividend",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "ts_code": "000001.SZ",
                    "end_date": "20251231",
                    "ann_date": "20260321",
                    "div_proc": "实施",
                    "record_date": "20260401",
                    "ex_date": None,
                    "pay_date": None,
                    "cash_div": "0",
                    "cash_div_tax": "0",
                    "stk_div": "1",
                }
            ],
        ),
    )

    assert batch.rows_rejected == 0
    row = batch.rows_normalized[0]
    assert row["end_date"] == date(2025, 12, 31)
    assert row["ann_date"] == date(2026, 3, 21)
    assert row["ex_date"] == date(2026, 4, 1)
    assert row["row_key_hash"] == build_dividend_row_key_hash(row)
    assert row["event_key_hash"] == build_dividend_event_key_hash(row)


def test_dividend_normalizer_rejects_rows_missing_required_keys() -> None:
    contract = get_sync_v2_contract("dividend")
    batch = SyncV2Normalizer().normalize(
        contract=contract,
        fetch_result=FetchResult(
            unit_id="u-dividend-invalid",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "ts_code": "000001.SZ",
                    "ann_date": None,
                    "div_proc": None,
                    "cash_div_tax": 0.36,
                }
            ],
        ),
    )

    assert batch.rows_normalized == []
    assert batch.rows_rejected == 1
    assert batch.rejected_reasons == {"ValueError": 1}
