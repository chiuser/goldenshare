from __future__ import annotations

from datetime import date

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
