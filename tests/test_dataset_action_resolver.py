from __future__ import annotations

from datetime import date

import pytest

from src.foundation.ingestion.errors import IngestionValidationError
from src.foundation.ingestion import DatasetActionRequest, DatasetActionResolver, DatasetTimeInput


def test_dataset_action_resolver_builds_point_plan_with_real_enum_defaults(mocker) -> None:
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key="dc_hot",
        action="maintain",
        time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 4, 24)),
    )

    plan = resolver.build_plan(request)

    assert plan.dataset_key == "dc_hot"
    assert plan.action == "maintain"
    assert plan.run_profile == "point_incremental"
    assert plan.planning.unit_count == 8
    assert {unit.request_params["hot_type"] for unit in plan.units} == {"人气榜", "飙升榜"}
    assert {unit.request_params["is_new"] for unit in plan.units} == {"Y"}


def test_dataset_action_resolver_builds_month_point_plan(mocker) -> None:
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key="broker_recommend",
        action="maintain",
        time_input=DatasetTimeInput(mode="point", month="2026-04"),
    )

    plan = resolver.build_plan(request)

    assert plan.run_profile == "point_incremental"
    assert plan.time_scope.mode == "point"
    assert plan.time_scope.start == "202604"
    assert plan.units[0].request_params == {"month": "202604"}


def test_dataset_action_resolver_rejects_month_window_plan_from_dates(mocker) -> None:
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key="index_weight",
        action="maintain",
        time_input=DatasetTimeInput(
            mode="range",
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 30),
        ),
        filters={"index_code": "000300.SH"},
    )

    with pytest.raises(ValueError, match="自然月窗口必须使用 start_month/end_month"):
        resolver.build_plan(request)


def test_dataset_action_resolver_builds_month_window_plan_from_month_keys(mocker) -> None:
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key="index_weight",
        action="maintain",
        time_input=DatasetTimeInput(
            mode="range",
            start_month="2026-04",
            end_month="2026-06",
        ),
        filters={"index_code": "000300.SH"},
    )

    plan = resolver.build_plan(request)

    assert plan.run_profile == "range_rebuild"
    assert plan.time_scope.mode == "range"
    assert plan.time_scope.start == "202604"
    assert plan.time_scope.end == "202606"
    assert plan.planning.unit_count == 1
    assert plan.units[0].request_params == {
        "index_code": "000300.SH",
        "start_date": "20260401",
        "end_date": "20260630",
    }


def test_dataset_action_resolver_builds_no_time_plan(mocker) -> None:
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key="stock_basic",
        action="maintain",
        time_input=DatasetTimeInput(mode="none"),
    )

    plan = resolver.build_plan(request)

    assert plan.run_profile == "snapshot_refresh"
    assert plan.time_scope.mode == "none"
    assert plan.planning.unit_count >= 1


def test_dataset_action_resolver_builds_index_basic_full_snapshot_with_pagination(mocker) -> None:
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key="index_basic",
        action="maintain",
        time_input=DatasetTimeInput(mode="none"),
    )

    plan = resolver.build_plan(request)

    assert plan.run_profile == "snapshot_refresh"
    assert plan.time_scope.mode == "none"
    assert plan.planning.unit_count == 1
    assert plan.units[0].request_params == {}
    assert plan.units[0].pagination_policy == "offset_limit"
    assert plan.units[0].page_limit == 6000


def test_dataset_action_resolver_builds_trade_cal_full_snapshot_without_hidden_date_window(mocker) -> None:
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key="trade_cal",
        action="maintain",
        time_input=DatasetTimeInput(mode="none"),
    )

    plan = resolver.build_plan(request)

    assert plan.run_profile == "snapshot_refresh"
    assert plan.time_scope.mode == "none"
    assert plan.planning.unit_count == 1
    assert plan.units[0].request_params == {"exchange": "SSE"}
    assert plan.units[0].pagination_policy == "offset_limit"
    assert plan.units[0].page_limit == 6000


def test_dataset_action_resolver_builds_index_basic_explicit_filters(mocker) -> None:
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key="index_basic",
        action="maintain",
        time_input=DatasetTimeInput(mode="none"),
        filters={
            "symbol": ["000300", "000905"],
            "market": "CSI",
            "category": "规模指数",
        },
    )

    plan = resolver.build_plan(request)

    assert plan.units[0].request_params == {
        "symbol": "000300,000905",
        "category": "规模指数",
        "market": "CSI",
    }


def test_dataset_action_resolver_builds_stk_period_week_range_by_calendar_friday(mocker) -> None:
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key="stk_period_bar_week",
        action="maintain",
        time_input=DatasetTimeInput(
            mode="range",
            start_date=date(2026, 4, 20),
            end_date=date(2026, 5, 8),
        ),
    )

    plan = resolver.build_plan(request)

    assert plan.run_profile == "range_rebuild"
    assert plan.planning.unit_count == 3
    assert [unit.trade_date for unit in plan.units] == [
        date(2026, 4, 24),
        date(2026, 5, 1),
        date(2026, 5, 8),
    ]
    assert [unit.request_params["trade_date"] for unit in plan.units] == ["20260424", "20260501", "20260508"]
    assert {unit.request_params["freq"] for unit in plan.units} == {"week"}


def test_dataset_action_resolver_builds_stk_period_month_range_by_calendar_month_end(mocker) -> None:
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key="stk_period_bar_month",
        action="maintain",
        time_input=DatasetTimeInput(
            mode="range",
            start_date=date(2026, 4, 20),
            end_date=date(2026, 5, 31),
        ),
    )

    plan = resolver.build_plan(request)

    assert plan.run_profile == "range_rebuild"
    assert plan.planning.unit_count == 2
    assert [unit.trade_date for unit in plan.units] == [date(2026, 4, 30), date(2026, 5, 31)]
    assert [unit.request_params["trade_date"] for unit in plan.units] == ["20260430", "20260531"]
    assert {unit.request_params["freq"] for unit in plan.units} == {"month"}


def test_dataset_action_resolver_rejects_invalid_stk_period_calendar_anchor(mocker) -> None:
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key="stk_period_bar_week",
        action="maintain",
        time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 4, 23)),
    )

    with pytest.raises(IngestionValidationError, match="当前数据集要求选择自然周周五"):
        resolver.build_plan(request)


def test_dataset_action_resolver_builds_cctv_news_range_by_natural_day(mocker) -> None:
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key="cctv_news",
        action="maintain",
        time_input=DatasetTimeInput(
            mode="range",
            start_date=date(2026, 4, 24),
            end_date=date(2026, 4, 26),
        ),
    )

    plan = resolver.build_plan(request)

    assert plan.dataset_key == "cctv_news"
    assert plan.run_profile == "range_rebuild"
    assert plan.planning.unit_count == 3
    assert [unit.request_params["date"] for unit in plan.units] == ["20260424", "20260425", "20260426"]
    assert {unit.pagination_policy for unit in plan.units} == {"offset_limit"}
    assert {unit.page_limit for unit in plan.units} == {400}


def test_dataset_action_resolver_builds_major_news_range_by_day_and_source_defaults(mocker) -> None:
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key="major_news",
        action="maintain",
        time_input=DatasetTimeInput(
            mode="range",
            start_date=date(2026, 4, 20),
            end_date=date(2026, 4, 22),
        ),
    )

    plan = resolver.build_plan(request)

    assert plan.dataset_key == "major_news"
    assert plan.run_profile == "range_rebuild"
    assert plan.planning.unit_count == 27
    assert {unit.request_params["src"] for unit in plan.units} == {
        "新华网",
        "凤凰财经",
        "同花顺",
        "新浪财经",
        "华尔街见闻",
        "中证网",
        "财新网",
        "第一财经",
        "财联社",
    }
    assert {unit.request_params["start_date"] for unit in plan.units} == {
        "2026-04-20 00:00:00",
        "2026-04-21 00:00:00",
        "2026-04-22 00:00:00",
    }
    assert {unit.request_params["end_date"] for unit in plan.units} == {
        "2026-04-20 23:59:59",
        "2026-04-21 23:59:59",
        "2026-04-22 23:59:59",
    }
    assert {unit.pagination_policy for unit in plan.units} == {"offset_limit"}
    assert {unit.page_limit for unit in plan.units} == {400}


def test_dataset_action_resolver_builds_major_news_with_selected_sources(mocker) -> None:
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key="major_news",
        action="maintain",
        time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 4, 24)),
        filters={"src": ["新华网", "财联社"]},
    )

    plan = resolver.build_plan(request)

    assert plan.run_profile == "point_incremental"
    assert plan.planning.unit_count == 2
    assert {unit.request_params["src"] for unit in plan.units} == {"新华网", "财联社"}
    assert {unit.request_params["start_date"] for unit in plan.units} == {"2026-04-24 00:00:00"}
    assert {unit.request_params["end_date"] for unit in plan.units} == {"2026-04-24 23:59:59"}
