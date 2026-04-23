from __future__ import annotations

from datetime import date

from src.foundation.services.sync_v2.contracts import FetchResult, RunRequest
from src.foundation.services.sync_v2.dataset_strategies.dc_hot import build_dc_hot_units
from src.foundation.services.sync_v2.dataset_strategies.kpl_concept_cons import build_kpl_concept_cons_units
from src.foundation.services.sync_v2.dataset_strategies.kpl_list import build_kpl_list_units
from src.foundation.services.sync_v2.dataset_strategies.ths_hot import build_ths_hot_units
from src.foundation.services.sync_v2.normalizer import SyncV2Normalizer
from src.foundation.services.sync_v2.registry import get_sync_v2_contract
from src.foundation.services.sync_v2.validator import ContractValidator


def test_ths_hot_point_incremental_expands_market_and_is_new() -> None:
    contract = get_sync_v2_contract("ths_hot")
    request = RunRequest(
        request_id="req-ths-hot",
        dataset_key="ths_hot",
        run_profile="point_incremental",
        trigger_source="test",
        trade_date=date(2026, 4, 2),
        params={"market": "热股,港股", "is_new": "Y,N"},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_ths_hot_units(validated, contract, dao=None, settings=None, session=None)

    assert len(units) == 4
    combos = sorted((u.request_params["market"], u.request_params["is_new"]) for u in units)
    assert combos == [("港股", "N"), ("港股", "Y"), ("热股", "N"), ("热股", "Y")]
    assert all(u.request_params["trade_date"] == "20260402" for u in units)
    assert all(u.page_limit == 2000 for u in units)


def test_ths_hot_normalizer_sets_default_query_context() -> None:
    contract = get_sync_v2_contract("ths_hot")
    batch = SyncV2Normalizer().normalize(
        contract=contract,
        fetch_result=FetchResult(
            unit_id="u-ths-hot",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "trade_date": "20260402",
                    "data_type": "热度",
                    "ts_code": "000001.SZ",
                    "rank_time": "10:00:00",
                    "ts_name": "平安银行",
                    "rank": 1,
                }
            ],
        ),
    )

    assert batch.rows_rejected == 0
    row = batch.rows_normalized[0]
    assert row["query_market"] == "__ALL__"
    assert row["query_is_new"] == "__ALL__"


def test_dc_hot_point_incremental_expands_three_enum_dimensions() -> None:
    contract = get_sync_v2_contract("dc_hot")
    request = RunRequest(
        request_id="req-dc-hot",
        dataset_key="dc_hot",
        run_profile="point_incremental",
        trigger_source="test",
        trade_date=date(2026, 4, 2),
        params={
            "market": "A股市场,ETF基金",
            "hot_type": "人气榜,飙升榜",
            "is_new": "N",
        },
    )
    validated = ContractValidator().validate(request, contract)
    units = build_dc_hot_units(validated, contract, dao=None, settings=None, session=None)

    assert len(units) == 4
    assert all(u.request_params["is_new"] == "N" for u in units)
    assert all(u.request_params["trade_date"] == "20260402" for u in units)


def test_dc_hot_normalizer_sets_default_query_context() -> None:
    contract = get_sync_v2_contract("dc_hot")
    batch = SyncV2Normalizer().normalize(
        contract=contract,
        fetch_result=FetchResult(
            unit_id="u-dc-hot",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "trade_date": "20260402",
                    "data_type": "热度",
                    "ts_code": "000001.SZ",
                    "rank_time": "10:00:00",
                    "ts_name": "平安银行",
                    "rank": 1,
                }
            ],
        ),
    )

    assert batch.rows_rejected == 0
    row = batch.rows_normalized[0]
    assert row["query_market"] == "__ALL__"
    assert row["query_hot_type"] == "__ALL__"
    assert row["query_is_new"] == "__ALL__"


def test_kpl_list_point_incremental_expands_tag_values() -> None:
    contract = get_sync_v2_contract("kpl_list")
    request = RunRequest(
        request_id="req-kpl-list",
        dataset_key="kpl_list",
        run_profile="point_incremental",
        trigger_source="test",
        trade_date=date(2026, 4, 2),
        params={"tag": "涨停,炸板"},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_kpl_list_units(validated, contract, dao=None, settings=None, session=None)

    assert len(units) == 2
    assert sorted(u.request_params["tag"] for u in units) == ["涨停", "炸板"]
    assert all(u.request_params["trade_date"] == "20260402" for u in units)
    assert all(u.page_limit == 8000 for u in units)


def test_kpl_concept_cons_point_incremental_builds_single_unit() -> None:
    contract = get_sync_v2_contract("kpl_concept_cons")
    request = RunRequest(
        request_id="req-kpl-cons",
        dataset_key="kpl_concept_cons",
        run_profile="point_incremental",
        trigger_source="test",
        trade_date=date(2026, 4, 2),
        params={"con_code": "GN001"},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_kpl_concept_cons_units(validated, contract, dao=None, settings=None, session=None)

    assert len(units) == 1
    assert units[0].request_params == {"trade_date": "20260402", "con_code": "GN001"}
    assert units[0].page_limit == 3000
