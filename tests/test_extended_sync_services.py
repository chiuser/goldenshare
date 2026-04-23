from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from src.foundation.services.sync_v2.contracts import RunRequest
from src.foundation.services.sync_v2.dataset_strategies.index_daily import build_index_daily_units
from src.foundation.services.sync_v2.dataset_strategies.index_daily_basic import build_index_daily_basic_units
from src.foundation.services.sync_v2.dataset_strategies.index_monthly import build_index_monthly_units
from src.foundation.services.sync_v2.dataset_strategies.index_weight import build_index_weight_units
from src.foundation.services.sync_v2.dataset_strategies.index_weekly import build_index_weekly_units
from src.foundation.services.sync_v2.dataset_strategies.stk_period_bar_adj_month import build_stk_period_bar_adj_month_units
from src.foundation.services.sync_v2.dataset_strategies.stk_period_bar_adj_week import build_stk_period_bar_adj_week_units
from src.foundation.services.sync_v2.dataset_strategies.stk_period_bar_month import build_stk_period_bar_month_units
from src.foundation.services.sync_v2.dataset_strategies.stk_period_bar_week import build_stk_period_bar_week_units
from src.foundation.services.sync_v2.registry import get_sync_v2_contract
from src.foundation.services.sync_v2.validator import ContractValidator


def _fake_dao(
    *,
    open_dates: list[date] | None = None,
    active_codes: list[str] | None = None,
    fallback_codes: list[str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        trade_calendar=SimpleNamespace(
            get_open_dates=lambda exchange, start_date, end_date: list(open_dates or [])
        ),
        index_series_active=SimpleNamespace(
            list_active_codes=lambda dataset_key: list(active_codes or [])
        ),
        index_basic=SimpleNamespace(
            get_active_indexes=lambda: [SimpleNamespace(ts_code=code) for code in (fallback_codes or [])]
        ),
    )


def test_index_daily_point_incremental_uses_active_index_pool() -> None:
    contract = get_sync_v2_contract("index_daily")
    request = RunRequest(
        request_id="req-index-daily-point",
        dataset_key="index_daily",
        run_profile="point_incremental",
        trigger_source="test",
        trade_date=date(2026, 3, 25),
        params={},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_index_daily_units(
        validated,
        contract,
        dao=_fake_dao(active_codes=["000001.SH", "399001.SZ"]),
        settings=SimpleNamespace(default_exchange="SSE"),
        session=None,
    )

    assert len(units) == 2
    assert sorted(u.request_params["ts_code"] for u in units) == ["000001.SH", "399001.SZ"]
    assert all(u.request_params["trade_date"] == "20260325" for u in units)
    assert all(u.page_limit == 8000 for u in units)


def test_index_daily_falls_back_to_index_basic_when_active_pool_empty() -> None:
    contract = get_sync_v2_contract("index_daily")
    request = RunRequest(
        request_id="req-index-daily-fallback",
        dataset_key="index_daily",
        run_profile="point_incremental",
        trigger_source="test",
        trade_date=date(2026, 3, 25),
        params={},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_index_daily_units(
        validated,
        contract,
        dao=_fake_dao(active_codes=[], fallback_codes=["000300.SH"]),
        settings=SimpleNamespace(default_exchange="SSE"),
        session=None,
    )

    assert len(units) == 1
    assert units[0].request_params == {"trade_date": "20260325", "ts_code": "000300.SH"}


def test_index_weekly_range_rebuild_compresses_to_week_end_anchors() -> None:
    contract = get_sync_v2_contract("index_weekly")
    request = RunRequest(
        request_id="req-index-weekly-range",
        dataset_key="index_weekly",
        run_profile="range_rebuild",
        trigger_source="test",
        start_date=date(2026, 3, 16),
        end_date=date(2026, 3, 27),
        params={"ts_code": "000001.SH"},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_index_weekly_units(
        validated,
        contract,
        dao=_fake_dao(
            open_dates=[
                date(2026, 3, 16),
                date(2026, 3, 17),
                date(2026, 3, 18),
                date(2026, 3, 19),
                date(2026, 3, 20),
                date(2026, 3, 23),
                date(2026, 3, 24),
                date(2026, 3, 25),
                date(2026, 3, 26),
                date(2026, 3, 27),
            ]
        ),
        settings=SimpleNamespace(default_exchange="SSE"),
        session=None,
    )

    assert len(units) == 2
    assert sorted(u.request_params["trade_date"] for u in units) == ["20260320", "20260327"]


def test_index_monthly_range_rebuild_compresses_to_month_end_anchor() -> None:
    contract = get_sync_v2_contract("index_monthly")
    request = RunRequest(
        request_id="req-index-monthly-range",
        dataset_key="index_monthly",
        run_profile="range_rebuild",
        trigger_source="test",
        start_date=date(2026, 3, 16),
        end_date=date(2026, 3, 31),
        params={"ts_code": "000001.SH"},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_index_monthly_units(
        validated,
        contract,
        dao=_fake_dao(
            open_dates=[
                date(2026, 3, 16),
                date(2026, 3, 17),
                date(2026, 3, 18),
                date(2026, 3, 19),
                date(2026, 3, 20),
                date(2026, 3, 23),
                date(2026, 3, 24),
                date(2026, 3, 25),
                date(2026, 3, 26),
                date(2026, 3, 27),
                date(2026, 3, 30),
                date(2026, 3, 31),
            ]
        ),
        settings=SimpleNamespace(default_exchange="SSE"),
        session=None,
    )

    assert len(units) == 1
    assert units[0].request_params["trade_date"] == "20260331"


def test_stk_period_bar_week_and_month_point_params() -> None:
    week_contract = get_sync_v2_contract("stk_period_bar_week")
    week_request = RunRequest(
        request_id="req-stk-week",
        dataset_key="stk_period_bar_week",
        run_profile="point_incremental",
        trigger_source="test",
        trade_date=date(2026, 3, 27),
        params={"ts_code": "000001.SZ"},
    )
    week_validated = ContractValidator().validate(week_request, week_contract)
    week_units = build_stk_period_bar_week_units(week_validated, week_contract, dao=None, settings=None, session=None)
    assert week_units[0].request_params == {"freq": "week", "ts_code": "000001.SZ", "trade_date": "20260327"}

    month_contract = get_sync_v2_contract("stk_period_bar_month")
    month_request = RunRequest(
        request_id="req-stk-month",
        dataset_key="stk_period_bar_month",
        run_profile="point_incremental",
        trigger_source="test",
        trade_date=date(2026, 3, 31),
        params={"ts_code": "000001.SZ"},
    )
    month_validated = ContractValidator().validate(month_request, month_contract)
    month_units = build_stk_period_bar_month_units(month_validated, month_contract, dao=None, settings=None, session=None)
    assert month_units[0].request_params == {"freq": "month", "ts_code": "000001.SZ", "trade_date": "20260331"}


def test_stk_period_bar_adj_week_and_month_point_params() -> None:
    week_contract = get_sync_v2_contract("stk_period_bar_adj_week")
    week_request = RunRequest(
        request_id="req-stk-adj-week",
        dataset_key="stk_period_bar_adj_week",
        run_profile="point_incremental",
        trigger_source="test",
        trade_date=date(2026, 3, 27),
        params={"ts_code": "000001.SZ"},
    )
    week_validated = ContractValidator().validate(week_request, week_contract)
    week_units = build_stk_period_bar_adj_week_units(
        week_validated, week_contract, dao=None, settings=None, session=None
    )
    assert week_units[0].request_params == {"freq": "week", "ts_code": "000001.SZ", "trade_date": "20260327"}

    month_contract = get_sync_v2_contract("stk_period_bar_adj_month")
    month_request = RunRequest(
        request_id="req-stk-adj-month",
        dataset_key="stk_period_bar_adj_month",
        run_profile="point_incremental",
        trigger_source="test",
        trade_date=date(2026, 3, 31),
        params={"ts_code": "000001.SZ"},
    )
    month_validated = ContractValidator().validate(month_request, month_contract)
    month_units = build_stk_period_bar_adj_month_units(
        month_validated, month_contract, dao=None, settings=None, session=None
    )
    assert month_units[0].request_params == {"freq": "month", "ts_code": "000001.SZ", "trade_date": "20260331"}


def test_index_weight_range_rebuild_builds_units_from_active_index_pool() -> None:
    contract = get_sync_v2_contract("index_weight")
    request = RunRequest(
        request_id="req-index-weight-range",
        dataset_key="index_weight",
        run_profile="range_rebuild",
        trigger_source="test",
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 31),
        params={},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_index_weight_units(
        validated,
        contract,
        dao=_fake_dao(active_codes=["000300.SH", "000905.SH"]),
        settings=SimpleNamespace(default_exchange="SSE"),
        session=None,
    )

    assert len(units) == 2
    assert sorted(unit.request_params["index_code"] for unit in units) == ["000300.SH", "000905.SH"]
    assert all(unit.request_params["start_date"] == "20260301" for unit in units)
    assert all(unit.request_params["end_date"] == "20260331" for unit in units)
    assert all(unit.page_limit == 6000 for unit in units)


def test_index_daily_basic_point_incremental_builds_single_unit() -> None:
    contract = get_sync_v2_contract("index_daily_basic")
    request = RunRequest(
        request_id="req-index-daily-basic",
        dataset_key="index_daily_basic",
        run_profile="point_incremental",
        trigger_source="test",
        trade_date=date(2026, 3, 25),
        params={},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_index_daily_basic_units(validated, contract, dao=None, settings=None, session=None)

    assert len(units) == 1
    assert units[0].request_params == {"trade_date": "20260325"}
    assert units[0].page_limit == 3000
