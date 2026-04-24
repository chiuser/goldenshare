from __future__ import annotations

from datetime import date

from src.foundation.services.sync_v2.contracts import FetchResult, RunRequest
from src.foundation.services.sync_v2.dataset_strategies.limit_cpt_list import build_limit_cpt_list_units
from src.foundation.services.sync_v2.dataset_strategies.limit_list_ths import build_limit_list_ths_units
from src.foundation.services.sync_v2.dataset_strategies.limit_step import build_limit_step_units
from src.foundation.services.sync_v2.normalizer import SyncV2Normalizer
from src.foundation.services.sync_v2.registry import get_sync_v2_contract
from src.foundation.services.sync_v2.validator import ContractValidator


def test_limit_list_ths_point_incremental_expands_enum_combinations() -> None:
    contract = get_sync_v2_contract("limit_list_ths")
    request = RunRequest(
        request_id="req-limit-list-ths",
        dataset_key="limit_list_ths",
        run_profile="point_incremental",
        trigger_source="test",
        trade_date=date(2026, 4, 3),
        params={"limit_type": "涨停池,炸板池", "market": "HS,GEM"},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_limit_list_ths_units(validated, contract, dao=None, settings=None, session=None)

    assert len(units) == 4
    combo_params = sorted((u.request_params["limit_type"], u.request_params["market"]) for u in units)
    assert combo_params == [("涨停池", "GEM"), ("涨停池", "HS"), ("炸板池", "GEM"), ("炸板池", "HS")]
    assert all(u.request_params["trade_date"] == "20260403" for u in units)
    assert all(u.page_limit == 4000 for u in units)


def test_limit_list_ths_point_incremental_expands_frontend_enum_lists() -> None:
    contract = get_sync_v2_contract("limit_list_ths")
    request = RunRequest(
        request_id="req-limit-list-ths-list",
        dataset_key="limit_list_ths",
        run_profile="point_incremental",
        trigger_source="test",
        trade_date=date(2026, 4, 3),
        params={"limit_type": ["涨停池", "炸板池"], "market": ["HS", "GEM"]},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_limit_list_ths_units(validated, contract, dao=None, settings=None, session=None)

    assert len(units) == 4
    combo_params = sorted((u.request_params["limit_type"], u.request_params["market"]) for u in units)
    assert combo_params == [("涨停池", "GEM"), ("涨停池", "HS"), ("炸板池", "GEM"), ("炸板池", "HS")]
    assert all(u.request_params["trade_date"] == "20260403" for u in units)


def test_limit_list_ths_normalizer_sets_query_context() -> None:
    contract = get_sync_v2_contract("limit_list_ths")
    batch = SyncV2Normalizer().normalize(
        contract=contract,
        fetch_result=FetchResult(
            unit_id="u-limit-list-ths",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "trade_date": "20260403",
                    "ts_code": "000001.SZ",
                    "name": "平安银行",
                    "price": "11.20",
                    "pct_chg": "10.01",
                    "limit_type": "涨停池",
                    "market_type": "HS",
                }
            ],
        ),
    )

    assert batch.rows_rejected == 0
    row = batch.rows_normalized[0]
    assert row["query_limit_type"] == "涨停池"
    assert row["query_market"] == "HS"


def test_limit_step_point_incremental_builds_single_unit() -> None:
    contract = get_sync_v2_contract("limit_step")
    request = RunRequest(
        request_id="req-limit-step",
        dataset_key="limit_step",
        run_profile="point_incremental",
        trigger_source="test",
        trade_date=date(2026, 4, 3),
        params={},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_limit_step_units(validated, contract, dao=None, settings=None, session=None)

    assert len(units) == 1
    assert units[0].request_params == {"trade_date": "20260403"}
    assert units[0].page_limit == 2000


def test_limit_cpt_list_point_incremental_builds_single_unit() -> None:
    contract = get_sync_v2_contract("limit_cpt_list")
    request = RunRequest(
        request_id="req-limit-cpt-list",
        dataset_key="limit_cpt_list",
        run_profile="point_incremental",
        trigger_source="test",
        trade_date=date(2026, 4, 3),
        params={},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_limit_cpt_list_units(validated, contract, dao=None, settings=None, session=None)

    assert len(units) == 1
    assert units[0].request_params == {"trade_date": "20260403"}
    assert units[0].page_limit == 2000
