from __future__ import annotations

from datetime import date

from src.scripts.backfill_top_list_reason_hash import find_top_list_reason_hash_conflicts
from src.foundation.services.sync_v2.contracts import FetchResult, RunRequest
from src.foundation.services.sync_v2.dataset_strategies.top_list import build_top_list_units
from src.foundation.services.sync_v2.normalizer import SyncV2Normalizer
from src.foundation.services.sync_v2.registry import get_sync_v2_contract
from src.foundation.services.sync_v2.validator import ContractValidator
from src.foundation.services.transform.top_list_reason import hash_top_list_reason, normalize_top_list_reason


def test_top_list_reason_hash_normalizes_before_hashing() -> None:
    assert normalize_top_list_reason("  异常\t波动  ") == "异常 波动"
    assert normalize_top_list_reason("ＡＢＣ　123") == "ABC 123"
    assert hash_top_list_reason("  异常\t波动  ") == hash_top_list_reason("异常 波动")


def test_top_list_point_incremental_builds_unit() -> None:
    contract = get_sync_v2_contract("top_list")
    request = RunRequest(
        request_id="req-top-list-point",
        dataset_key="top_list",
        run_profile="point_incremental",
        trigger_source="test",
        trade_date=date(2026, 3, 24),
        params={"ts_code": "000001.sz"},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_top_list_units(validated, contract, dao=None, settings=None, session=None)

    assert len(units) == 1
    assert units[0].request_params == {"trade_date": "20260324", "ts_code": "000001.SZ"}
    assert units[0].pagination_policy == "offset_limit"
    assert units[0].page_limit == 10000


def test_top_list_normalizer_adds_reason_hash_and_pct_chg() -> None:
    contract = get_sync_v2_contract("top_list")
    batch = SyncV2Normalizer().normalize(
        contract=contract,
        fetch_result=FetchResult(
            unit_id="u-top-list",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260324",
                    "reason": "  异常\t波动  ",
                    "pct_change": "1.23",
                }
            ],
        ),
    )
    row = batch.rows_normalized[0]
    assert row["trade_date"] == date(2026, 3, 24)
    assert row["reason_hash"] == hash_top_list_reason("异常 波动")
    assert row["pct_chg"] == row["pct_change"]


def test_find_top_list_reason_hash_conflicts_detects_normalized_duplicates(mocker) -> None:
    session = mocker.Mock()
    session.execute.return_value = [
        ("000001.SZ", date(2026, 3, 24), "异常  波动"),
        ("000001.SZ", date(2026, 3, 24), "异常\t波动"),
    ]

    conflicts = find_top_list_reason_hash_conflicts(session)

    assert len(conflicts) == 1
    ts_code, trade_date, reason_hash, count = conflicts[0]
    assert ts_code == "000001.SZ"
    assert trade_date == date(2026, 3, 24)
    assert reason_hash == hash_top_list_reason("异常 波动")
    assert count == 2
