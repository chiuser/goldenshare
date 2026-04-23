from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from src.foundation.services.sync_v2.contracts import FetchResult, RunRequest
from src.foundation.services.sync_v2.dataset_strategies.dc_daily import build_dc_daily_units
from src.foundation.services.sync_v2.dataset_strategies.dc_index import build_dc_index_units
from src.foundation.services.sync_v2.dataset_strategies.dc_member import build_dc_member_units
from src.foundation.services.sync_v2.dataset_strategies.ths_daily import build_ths_daily_units
from src.foundation.services.sync_v2.dataset_strategies.ths_index import build_ths_index_units
from src.foundation.services.sync_v2.dataset_strategies.ths_member import build_ths_member_units
from src.foundation.services.sync_v2.normalizer import SyncV2Normalizer
from src.foundation.services.sync_v2.registry import get_sync_v2_contract
from src.foundation.services.sync_v2.validator import ContractValidator


def _fake_dao(open_dates: list[date]) -> SimpleNamespace:
    return SimpleNamespace(
        trade_calendar=SimpleNamespace(
            get_open_dates=lambda exchange, start_date, end_date: list(open_dates)
        )
    )


def test_ths_index_snapshot_refresh_builds_single_unit_with_filters() -> None:
    contract = get_sync_v2_contract("ths_index")
    request = RunRequest(
        request_id="req-ths-index",
        dataset_key="ths_index",
        run_profile="snapshot_refresh",
        trigger_source="test",
        params={"ts_code": "885001.TI", "exchange": "A", "type": "N"},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_ths_index_units(validated, contract, dao=None, settings=None, session=None)

    assert len(units) == 1
    assert units[0].request_params == {"ts_code": "885001.TI", "exchange": "A", "type": "N"}


def test_ths_member_snapshot_refresh_builds_single_unit_with_filters() -> None:
    contract = get_sync_v2_contract("ths_member")
    request = RunRequest(
        request_id="req-ths-member",
        dataset_key="ths_member",
        run_profile="snapshot_refresh",
        trigger_source="test",
        params={"ts_code": "885001.TI", "con_code": "000001.SZ"},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_ths_member_units(validated, contract, dao=None, settings=None, session=None)

    assert len(units) == 1
    assert units[0].request_params == {"ts_code": "885001.TI", "con_code": "000001.SZ"}
    assert units[0].page_limit == 5000


def test_ths_daily_point_and_range_build_expected_params() -> None:
    contract = get_sync_v2_contract("ths_daily")
    point_request = RunRequest(
        request_id="req-ths-daily-point",
        dataset_key="ths_daily",
        run_profile="point_incremental",
        trigger_source="test",
        trade_date=date(2026, 4, 1),
        params={"ts_code": "885001.TI"},
    )
    point_validated = ContractValidator().validate(point_request, contract)
    point_units = build_ths_daily_units(point_validated, contract, dao=None, settings=None, session=None)
    assert point_units[0].request_params == {"ts_code": "885001.TI", "trade_date": "20260401"}

    range_request = RunRequest(
        request_id="req-ths-daily-range",
        dataset_key="ths_daily",
        run_profile="range_rebuild",
        trigger_source="test",
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 31),
        params={"ts_code": "885001.TI"},
    )
    range_validated = ContractValidator().validate(range_request, contract)
    range_units = build_ths_daily_units(
        range_validated,
        contract,
        dao=_fake_dao([date(2026, 3, 31)]),
        settings=SimpleNamespace(default_exchange="SSE"),
        session=None,
    )
    assert len(range_units) == 1
    assert range_units[0].request_params == {
        "ts_code": "885001.TI",
        "start_date": "20260301",
        "end_date": "20260331",
    }


def test_dc_index_point_and_range_build_expected_params() -> None:
    contract = get_sync_v2_contract("dc_index")
    point_request = RunRequest(
        request_id="req-dc-index-point",
        dataset_key="dc_index",
        run_profile="point_incremental",
        trigger_source="test",
        trade_date=date(2026, 4, 1),
        params={"idx_type": "concept"},
    )
    point_validated = ContractValidator().validate(point_request, contract)
    point_units = build_dc_index_units(point_validated, contract, dao=None, settings=None, session=None)
    assert point_units[0].request_params == {"trade_date": "20260401", "idx_type": "concept"}

    range_request = RunRequest(
        request_id="req-dc-index-range",
        dataset_key="dc_index",
        run_profile="range_rebuild",
        trigger_source="test",
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 31),
        params={"idx_type": "concept"},
    )
    range_validated = ContractValidator().validate(range_request, contract)
    range_units = build_dc_index_units(
        range_validated,
        contract,
        dao=_fake_dao([date(2026, 3, 30), date(2026, 3, 31)]),
        settings=SimpleNamespace(default_exchange="SSE"),
        session=None,
    )
    assert len(range_units) == 2
    assert sorted(unit.request_params["trade_date"] for unit in range_units) == ["20260330", "20260331"]
    assert all(unit.request_params["idx_type"] == "concept" for unit in range_units)


def test_dc_member_and_dc_daily_point_incremental_build_expected_params() -> None:
    member_contract = get_sync_v2_contract("dc_member")
    member_request = RunRequest(
        request_id="req-dc-member",
        dataset_key="dc_member",
        run_profile="point_incremental",
        trigger_source="test",
        trade_date=date(2026, 4, 1),
        params={"ts_code": "BK001"},
    )
    member_validated = ContractValidator().validate(member_request, member_contract)
    member_units = build_dc_member_units(member_validated, member_contract, dao=None, settings=None, session=None)
    assert member_units[0].request_params == {"trade_date": "20260401", "ts_code": "BK001"}

    daily_contract = get_sync_v2_contract("dc_daily")
    daily_request = RunRequest(
        request_id="req-dc-daily",
        dataset_key="dc_daily",
        run_profile="point_incremental",
        trigger_source="test",
        trade_date=date(2026, 4, 1),
        params={"idx_type": "concept", "ts_code": "BK001"},
    )
    daily_validated = ContractValidator().validate(daily_request, daily_contract)
    daily_units = build_dc_daily_units(daily_validated, daily_contract, dao=None, settings=None, session=None)
    assert daily_units[0].request_params == {"ts_code": "BK001", "idx_type": "concept", "trade_date": "20260401"}


def test_dc_daily_normalizer_keeps_required_fields() -> None:
    contract = get_sync_v2_contract("dc_daily")
    batch = SyncV2Normalizer().normalize(
        contract=contract,
        fetch_result=FetchResult(
            unit_id="u-dc-daily",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[{"trade_date": "20260401", "ts_code": "BK001", "close": "1"}],
        ),
    )
    assert batch.rows_rejected == 0
    assert batch.rows_normalized[0]["trade_date"] == date(2026, 4, 1)
