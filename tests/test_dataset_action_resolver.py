from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from src.foundation.ingestion.errors import IngestionPlanningError
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


@pytest.mark.parametrize(
    ("dataset_key", "filters", "expected_request_params"),
    (
        ("daily", {}, {"trade_date": "20260424"}),
        ("adj_factor", {}, {"trade_date": "20260424"}),
        ("cyq_perf", {}, {"trade_date": "20260424"}),
        ("fund_daily", {}, {"trade_date": "20260424"}),
        ("index_daily", {"ts_code": "000300.SH"}, {"ts_code": "000300.SH", "trade_date": "20260424"}),
        ("index_daily_basic", {}, {"trade_date": "20260424"}),
    ),
)
def test_dataset_action_resolver_does_not_inject_dead_exchange_filter(
    mocker,
    dataset_key: str,
    filters: dict[str, str],
    expected_request_params: dict[str, str],
) -> None:
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key=dataset_key,
        action="maintain",
        time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 4, 24)),
        filters=filters,
    )

    plan = resolver.build_plan(request)

    assert "exchange" not in plan.filters
    if "ts_code" in filters:
        assert plan.filters["ts_code"] == filters["ts_code"]
    assert plan.filters["trade_date"] == date(2026, 4, 24)
    assert plan.units[0].request_params == expected_request_params
    assert "exchange" not in plan.units[0].request_params


def test_index_daily_default_request_does_not_expand_active_pool(mocker) -> None:
    fake_dao = SimpleNamespace(
        trade_calendar=SimpleNamespace(),
        index_series_active=SimpleNamespace(list_active_codes=mocker.Mock(side_effect=AssertionError("active pool must not be queried"))),
        index_basic=SimpleNamespace(get_active_indexes=mocker.Mock(side_effect=AssertionError("index_basic fallback must not be queried"))),
    )
    mocker.patch("src.foundation.ingestion.unit_planner.DAOFactory", return_value=fake_dao)
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key="index_daily",
        action="maintain",
        time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 4, 24)),
    )

    plan = resolver.build_plan(request)

    assert plan.planning.unit_count == 1
    assert plan.units[0].request_params == {"trade_date": "20260424"}
    assert "ts_code" not in plan.units[0].request_params


@pytest.mark.parametrize(
    "dataset_key",
    ("daily", "adj_factor", "cyq_perf", "fund_daily", "index_daily", "index_daily_basic"),
)
def test_dataset_action_resolver_rejects_removed_exchange_filter(mocker, dataset_key: str) -> None:
    resolver = DatasetActionResolver(mocker.Mock())
    filters = {"exchange": "SSE"}
    if dataset_key == "index_daily":
        filters["ts_code"] = "000300.SH"
    request = DatasetActionRequest(
        dataset_key=dataset_key,
        action="maintain",
        time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 4, 24)),
        filters=filters,
    )

    with pytest.raises(IngestionValidationError, match="存在未定义参数：exchange"):
        resolver.build_plan(request)


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


def test_index_weight_explicit_index_code_does_not_query_universe(mocker) -> None:
    fake_dao = SimpleNamespace(
        index_series_active=SimpleNamespace(list_active_codes=mocker.Mock()),
        index_basic=SimpleNamespace(get_active_indexes=mocker.Mock()),
    )
    mocker.patch("src.foundation.ingestion.unit_planner.DAOFactory", return_value=fake_dao)
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key="index_weight",
        action="maintain",
        time_input=DatasetTimeInput(mode="range", start_month="2026-04", end_month="2026-04"),
        filters={"index_code": "000905.SH,000300.SH"},
    )

    plan = resolver.build_plan(request)

    assert plan.planning.universe_policy == "pool"
    assert [unit.request_params["index_code"] for unit in plan.units] == ["000300.SH", "000905.SH"]
    fake_dao.index_series_active.list_active_codes.assert_not_called()
    fake_dao.index_basic.get_active_indexes.assert_not_called()


def test_index_weight_uses_active_pool_before_index_basic(mocker) -> None:
    fake_dao = SimpleNamespace(
        index_series_active=SimpleNamespace(list_active_codes=mocker.Mock(return_value=["000905.SH", "000300.SH"])),
        index_basic=SimpleNamespace(get_active_indexes=mocker.Mock()),
    )
    mocker.patch("src.foundation.ingestion.unit_planner.DAOFactory", return_value=fake_dao)
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key="index_weight",
        action="maintain",
        time_input=DatasetTimeInput(mode="range", start_month="2026-04", end_month="2026-04"),
    )

    plan = resolver.build_plan(request)

    assert [unit.request_params["index_code"] for unit in plan.units] == ["000300.SH", "000905.SH"]
    fake_dao.index_series_active.list_active_codes.assert_called_once_with("index_weight")
    fake_dao.index_basic.get_active_indexes.assert_not_called()


def test_index_weight_falls_back_to_active_index_basic(mocker) -> None:
    fake_dao = SimpleNamespace(
        index_series_active=SimpleNamespace(list_active_codes=mocker.Mock(return_value=[])),
        index_basic=SimpleNamespace(
            get_active_indexes=mocker.Mock(
                return_value=[
                    SimpleNamespace(ts_code="399001.SZ"),
                    SimpleNamespace(ts_code="000300.SH"),
                    SimpleNamespace(ts_code=None),
                ]
            )
        ),
    )
    mocker.patch("src.foundation.ingestion.unit_planner.DAOFactory", return_value=fake_dao)
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key="index_weight",
        action="maintain",
        time_input=DatasetTimeInput(mode="range", start_month="2026-04", end_month="2026-04"),
    )

    plan = resolver.build_plan(request)

    assert [unit.request_params["index_code"] for unit in plan.units] == ["000300.SH", "399001.SZ"]
    fake_dao.index_series_active.list_active_codes.assert_called_once_with("index_weight")
    fake_dao.index_basic.get_active_indexes.assert_called_once_with()


def test_index_weight_rejects_empty_universe(mocker) -> None:
    fake_dao = SimpleNamespace(
        index_series_active=SimpleNamespace(list_active_codes=mocker.Mock(return_value=[])),
        index_basic=SimpleNamespace(get_active_indexes=mocker.Mock(return_value=[])),
    )
    mocker.patch("src.foundation.ingestion.unit_planner.DAOFactory", return_value=fake_dao)
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key="index_weight",
        action="maintain",
        time_input=DatasetTimeInput(mode="range", start_month="2026-04", end_month="2026-04"),
    )

    with pytest.raises(IngestionPlanningError, match="指数权重未找到可维护的指数代码"):
        resolver.build_plan(request)


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


def test_dataset_action_resolver_builds_bse_mapping_full_snapshot_with_optional_filters(mocker) -> None:
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key="bse_mapping",
        action="maintain",
        time_input=DatasetTimeInput(mode="none"),
        filters={"o_code": "838163.BJ"},
    )

    plan = resolver.build_plan(request)

    assert plan.run_profile == "snapshot_refresh"
    assert plan.time_scope.mode == "none"
    assert plan.planning.unit_count == 1
    assert plan.units[0].request_params == {"o_code": "838163.BJ"}
    assert plan.units[0].pagination_policy == "offset_limit"
    assert plan.units[0].page_limit == 1000


def test_dataset_action_resolver_builds_bak_basic_point_plan(mocker) -> None:
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key="bak_basic",
        action="maintain",
        time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 4, 24)),
        filters={"ts_code": "000001.sz"},
    )

    plan = resolver.build_plan(request)

    assert plan.run_profile == "point_incremental"
    assert plan.time_scope.mode == "point"
    assert plan.planning.unit_count == 1
    assert plan.units[0].request_params == {"trade_date": "20260424", "ts_code": "000001.SZ"}
    assert plan.units[0].pagination_policy == "offset_limit"
    assert plan.units[0].page_limit == 7000


def test_dataset_action_resolver_builds_bak_basic_range_plan_by_open_days(mocker) -> None:
    fake_dao = SimpleNamespace(
        trade_calendar=SimpleNamespace(
            get_open_dates=mocker.Mock(return_value=[date(2026, 4, 22), date(2026, 4, 23), date(2026, 4, 24)])
        )
    )
    mocker.patch("src.foundation.ingestion.unit_planner.DAOFactory", return_value=fake_dao)
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key="bak_basic",
        action="maintain",
        time_input=DatasetTimeInput(mode="range", start_date=date(2026, 4, 21), end_date=date(2026, 4, 24)),
        filters={"ts_code": "000001.sz"},
    )

    plan = resolver.build_plan(request)

    assert plan.run_profile == "range_rebuild"
    assert plan.time_scope.mode == "range"
    assert plan.planning.unit_count == 3
    assert [unit.trade_date for unit in plan.units] == [date(2026, 4, 22), date(2026, 4, 23), date(2026, 4, 24)]
    assert [unit.request_params for unit in plan.units] == [
        {"trade_date": "20260422", "ts_code": "000001.SZ"},
        {"trade_date": "20260423", "ts_code": "000001.SZ"},
        {"trade_date": "20260424", "ts_code": "000001.SZ"},
    ]
    fake_dao.trade_calendar.get_open_dates.assert_called_once_with("SSE", date(2026, 4, 21), date(2026, 4, 24))
    assert {unit.pagination_policy for unit in plan.units} == {"offset_limit"}
    assert {unit.page_limit for unit in plan.units} == {7000}


def test_dataset_action_resolver_builds_stock_company_default_exchange_fanout(mocker) -> None:
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key="stock_company",
        action="maintain",
        time_input=DatasetTimeInput(mode="none"),
    )

    plan = resolver.build_plan(request)

    assert plan.run_profile == "snapshot_refresh"
    assert plan.time_scope.mode == "none"
    assert plan.planning.unit_count == 3
    assert [unit.request_params for unit in plan.units] == [
        {"exchange": "SSE"},
        {"exchange": "SZSE"},
        {"exchange": "BSE"},
    ]
    assert {unit.pagination_policy for unit in plan.units} == {"offset_limit"}
    assert {unit.page_limit for unit in plan.units} == {4500}


def test_dataset_action_resolver_builds_stock_company_for_explicit_ts_code_without_exchange_fanout(mocker) -> None:
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key="stock_company",
        action="maintain",
        time_input=DatasetTimeInput(mode="none"),
        filters={"ts_code": "000001.SZ", "exchange": ["SZSE", "SSE"]},
    )

    plan = resolver.build_plan(request)

    assert plan.planning.unit_count == 1
    assert plan.units[0].request_params == {"ts_code": "000001.SZ"}


def test_dataset_action_resolver_builds_namechange_snapshot_plan_without_date_params(mocker) -> None:
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key="namechange",
        action="maintain",
        time_input=DatasetTimeInput(mode="none"),
        filters={"ts_code": "000001.sz"},
    )

    plan = resolver.build_plan(request)

    assert plan.run_profile == "snapshot_refresh"
    assert plan.time_scope.mode == "none"
    assert plan.planning.unit_count == 1
    assert plan.units[0].request_params == {"ts_code": "000001.SZ"}
    assert plan.units[0].pagination_policy == "offset_limit"
    assert plan.units[0].page_limit == 1000


def test_dataset_action_resolver_builds_namechange_full_snapshot_plan_without_params(mocker) -> None:
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key="namechange",
        action="maintain",
        time_input=DatasetTimeInput(mode="none"),
    )

    plan = resolver.build_plan(request)

    assert plan.run_profile == "snapshot_refresh"
    assert plan.time_scope.mode == "none"
    assert plan.planning.unit_count == 1
    assert plan.units[0].request_params == {}
    assert plan.units[0].pagination_policy == "offset_limit"
    assert plan.units[0].page_limit == 1000


def test_dataset_action_resolver_builds_st_snapshot_plan_without_source_date_params(mocker) -> None:
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key="st",
        action="maintain",
        time_input=DatasetTimeInput(mode="none"),
        filters={},
    )

    plan = resolver.build_plan(request)

    assert plan.run_profile == "snapshot_refresh"
    assert plan.time_scope.mode == "none"
    assert plan.planning.unit_count == 1
    assert plan.units[0].request_params == {}
    assert plan.units[0].pagination_policy == "offset_limit"
    assert plan.units[0].page_limit == 1000


def test_dataset_action_resolver_builds_st_snapshot_plan_with_ts_code_filter(mocker) -> None:
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key="st",
        action="maintain",
        time_input=DatasetTimeInput(mode="none"),
        filters={"ts_code": "000001.sz"},
    )

    plan = resolver.build_plan(request)

    assert plan.run_profile == "snapshot_refresh"
    assert plan.time_scope.mode == "none"
    assert plan.planning.unit_count == 1
    assert plan.units[0].request_params == {"ts_code": "000001.SZ"}
    assert plan.units[0].pagination_policy == "offset_limit"
    assert plan.units[0].page_limit == 1000


def test_dataset_action_resolver_builds_stock_company_for_selected_exchanges(mocker) -> None:
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key="stock_company",
        action="maintain",
        time_input=DatasetTimeInput(mode="none"),
        filters={"exchange": ["BSE", "SSE"]},
    )

    plan = resolver.build_plan(request)

    assert plan.planning.unit_count == 2
    assert [unit.request_params for unit in plan.units] == [
        {"exchange": "SSE"},
        {"exchange": "BSE"},
    ]


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


def test_dataset_action_resolver_builds_news_range_by_day_and_source_defaults(mocker) -> None:
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key="news",
        action="maintain",
        time_input=DatasetTimeInput(
            mode="range",
            start_date=date(2026, 4, 20),
            end_date=date(2026, 4, 21),
        ),
    )

    plan = resolver.build_plan(request)

    assert plan.dataset_key == "news"
    assert plan.run_profile == "range_rebuild"
    assert plan.planning.unit_count == 18
    assert {unit.request_params["src"] for unit in plan.units} == {
        "sina",
        "wallstreetcn",
        "10jqka",
        "eastmoney",
        "yuncaijing",
        "fenghuang",
        "jinrongjie",
        "cls",
        "yicai",
    }
    assert {unit.request_params["start_date"] for unit in plan.units} == {
        "2026-04-20 00:00:00",
        "2026-04-21 00:00:00",
    }
    assert {unit.request_params["end_date"] for unit in plan.units} == {
        "2026-04-20 23:59:59",
        "2026-04-21 23:59:59",
    }
    assert {unit.pagination_policy for unit in plan.units} == {"offset_limit"}
    assert {unit.page_limit for unit in plan.units} == {1500}


def test_dataset_action_resolver_builds_news_with_selected_sources(mocker) -> None:
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key="news",
        action="maintain",
        time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 4, 24)),
        filters={"src": ["sina", "cls"]},
    )

    plan = resolver.build_plan(request)

    assert plan.run_profile == "point_incremental"
    assert plan.planning.unit_count == 2
    assert {unit.request_params["src"] for unit in plan.units} == {"sina", "cls"}
    assert {unit.request_params["start_date"] for unit in plan.units} == {"2026-04-24 00:00:00"}
    assert {unit.request_params["end_date"] for unit in plan.units} == {"2026-04-24 23:59:59"}
