from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from src.foundation.ingestion.errors import IngestionPlanningError
from src.foundation.ingestion.errors import IngestionValidationError
from src.foundation.ingestion import DatasetActionRequest, DatasetActionResolver, DatasetTimeInput
from src.foundation.ingestion.request_builders import _index_daily_params


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
    assert plan.planning.unit_count == 6
    assert {unit.request_params["market"] for unit in plan.units} == {"A股市场", "ETF基金", "港股市场"}
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


def test_index_daily_default_point_request_uses_index_daily_raw_request_pool(mocker) -> None:
    fake_dao = SimpleNamespace(
        trade_calendar=SimpleNamespace(),
        index_series_active=SimpleNamespace(list_active_codes=mocker.Mock(return_value=["000300.SH", "000001.SH"])),
        index_basic=SimpleNamespace(
            get_active_indexes=mocker.Mock(side_effect=AssertionError("index basic must not drive index_daily requests"))
        ),
    )
    mocker.patch("src.foundation.ingestion.unit_planner.DAOFactory", return_value=fake_dao)
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key="index_daily",
        action="maintain",
        time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 4, 24)),
    )

    plan = resolver.build_plan(request)

    assert plan.planning.unit_count == 2
    assert all("ts_code" in unit.request_params for unit in plan.units)
    assert [unit.request_params for unit in plan.units] == [
        {"ts_code": "000001.SH", "trade_date": "20260424"},
        {"ts_code": "000300.SH", "trade_date": "20260424"},
    ]
    fake_dao.index_series_active.list_active_codes.assert_called_once_with("index_daily_raw")
    fake_dao.index_basic.get_active_indexes.assert_not_called()


def test_index_daily_default_range_request_uses_index_daily_raw_request_pool(mocker) -> None:
    fake_dao = SimpleNamespace(
        trade_calendar=SimpleNamespace(),
        index_series_active=SimpleNamespace(list_active_codes=mocker.Mock(return_value=["000300.SH"])),
        index_basic=SimpleNamespace(
            get_active_indexes=mocker.Mock(side_effect=AssertionError("index basic must not drive index_daily requests"))
        ),
    )
    mocker.patch("src.foundation.ingestion.unit_planner.DAOFactory", return_value=fake_dao)
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key="index_daily",
        action="maintain",
        time_input=DatasetTimeInput(mode="range", start_date=date(2026, 4, 20), end_date=date(2026, 4, 24)),
    )

    plan = resolver.build_plan(request)

    assert plan.planning.unit_count == 1
    assert plan.units[0].request_params == {
        "ts_code": "000300.SH",
        "start_date": "20260420",
        "end_date": "20260424",
    }
    fake_dao.index_series_active.list_active_codes.assert_called_once_with("index_daily_raw")
    fake_dao.index_basic.get_active_indexes.assert_not_called()


def test_index_daily_request_builder_requires_ts_code() -> None:
    request = SimpleNamespace(
        run_profile="point_incremental",
        trade_date=date(2026, 4, 24),
        start_date=None,
        end_date=None,
        params={},
    )

    with pytest.raises(ValueError, match="指数日线缺少指数代码"):
        _index_daily_params(request, date(2026, 4, 24), {})


def test_dataset_action_resolver_reports_required_filter_with_display_label(mocker) -> None:
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key="stk_mins",
        action="maintain",
        time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 4, 24)),
        filters={},
    )

    with pytest.raises(IngestionValidationError, match="缺少必填参数：分钟周期"):
        resolver.build_plan(request)


def test_stk_mins_default_request_uses_tushare_active_equity_pool(mocker) -> None:
    fake_dao = SimpleNamespace(
        security=SimpleNamespace(
            get_active_equities=mocker.Mock(
                return_value=[
                    SimpleNamespace(ts_code="600000.SH", name="浦发银行", source="biying"),
                    SimpleNamespace(ts_code="000002.SZ", name="万科A", source="tushare"),
                    SimpleNamespace(ts_code="000001.SZ", name="平安银行", source="tushare"),
                ]
            ),
            get_by_ts_code=mocker.Mock(side_effect=AssertionError("default stk_mins requests must use the active equity pool")),
        )
    )
    mocker.patch("src.foundation.ingestion.unit_planner.DAOFactory", return_value=fake_dao)
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key="stk_mins",
        action="maintain",
        time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 4, 24)),
        filters={"freq": ["60min", "1min"]},
    )

    plan = resolver.build_plan(request)

    assert plan.run_profile == "point_incremental"
    assert plan.planning.unit_count == 4
    assert [unit.request_params for unit in plan.units] == [
        {
            "ts_code": "000001.SZ",
            "freq": "1min",
            "start_date": "2026-04-24 09:00:00",
            "end_date": "2026-04-24 19:00:00",
        },
        {
            "ts_code": "000001.SZ",
            "freq": "60min",
            "start_date": "2026-04-24 09:00:00",
            "end_date": "2026-04-24 19:00:00",
        },
        {
            "ts_code": "000002.SZ",
            "freq": "1min",
            "start_date": "2026-04-24 09:00:00",
            "end_date": "2026-04-24 19:00:00",
        },
        {
            "ts_code": "000002.SZ",
            "freq": "60min",
            "start_date": "2026-04-24 09:00:00",
            "end_date": "2026-04-24 19:00:00",
        },
    ]
    assert [unit.trade_date for unit in plan.units] == [date(2026, 4, 24)] * 4
    assert {unit.progress_context.get("security_name") for unit in plan.units} == {"平安银行", "万科A"}
    fake_dao.security.get_active_equities.assert_called_once_with()
    fake_dao.security.get_by_ts_code.assert_not_called()


def test_stk_mins_default_request_falls_back_to_all_active_equities_when_no_tushare_source(mocker) -> None:
    fake_dao = SimpleNamespace(
        security=SimpleNamespace(
            get_active_equities=mocker.Mock(
                return_value=[
                    SimpleNamespace(ts_code="600000.SH", name="浦发银行", source="biying"),
                    SimpleNamespace(ts_code="000001.SZ", name="平安银行", source="manual"),
                ]
            ),
            get_by_ts_code=mocker.Mock(side_effect=AssertionError("default stk_mins requests must use the active equity pool")),
        )
    )
    mocker.patch("src.foundation.ingestion.unit_planner.DAOFactory", return_value=fake_dao)
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key="stk_mins",
        action="maintain",
        time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 4, 24)),
        filters={"freq": ["30min"]},
    )

    plan = resolver.build_plan(request)

    assert plan.planning.unit_count == 2
    assert [unit.request_params["ts_code"] for unit in plan.units] == ["000001.SZ", "600000.SH"]
    assert {unit.request_params["freq"] for unit in plan.units} == {"30min"}
    fake_dao.security.get_active_equities.assert_called_once_with()
    fake_dao.security.get_by_ts_code.assert_not_called()


def test_stk_mins_explicit_codes_bypass_active_pool_and_build_range_window(mocker) -> None:
    fake_dao = SimpleNamespace(
        security=SimpleNamespace(
            get_active_equities=mocker.Mock(side_effect=AssertionError("explicit stk_mins requests must not scan the active equity pool")),
            get_by_ts_code=mocker.Mock(
                side_effect=lambda code: SimpleNamespace(name={"000001.SZ": "平安银行", "600000.SH": "浦发银行"}.get(code))
            ),
        )
    )
    mocker.patch("src.foundation.ingestion.unit_planner.DAOFactory", return_value=fake_dao)
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key="stk_mins",
        action="maintain",
        time_input=DatasetTimeInput(mode="range", start_date=date(2026, 4, 20), end_date=date(2026, 4, 24)),
        filters={"ts_code": "600000.sh,000001.sz", "freq": ["30min"]},
    )

    plan = resolver.build_plan(request)

    assert plan.run_profile == "range_rebuild"
    assert plan.planning.unit_count == 2
    assert [unit.request_params for unit in plan.units] == [
        {
            "ts_code": "000001.SZ",
            "freq": "30min",
            "start_date": "2026-04-20 09:00:00",
            "end_date": "2026-04-24 19:00:00",
        },
        {
            "ts_code": "600000.SH",
            "freq": "30min",
            "start_date": "2026-04-20 09:00:00",
            "end_date": "2026-04-24 19:00:00",
        },
    ]
    assert [unit.trade_date for unit in plan.units] == [None, None]
    assert {unit.progress_context.get("security_name") for unit in plan.units} == {"平安银行", "浦发银行"}
    fake_dao.security.get_active_equities.assert_not_called()
    assert [call.args[0] for call in fake_dao.security.get_by_ts_code.call_args_list] == ["000001.SZ", "600000.SH"]


def _mock_biying_stock_pool_session(mocker, rows: list[SimpleNamespace]):
    session = mocker.Mock()
    result = mocker.Mock()
    result.all.return_value = rows
    session.execute.return_value = result
    return session


def test_biying_equity_daily_default_request_uses_raw_biying_stock_pool_and_adj_types(mocker) -> None:
    resolver = DatasetActionResolver(
        _mock_biying_stock_pool_session(
            mocker,
            [
                SimpleNamespace(dm="000001", mc="平安银行"),
                SimpleNamespace(dm="000002", mc="万科A"),
            ],
        )
    )
    request = DatasetActionRequest(
        dataset_key="biying_equity_daily",
        action="maintain",
        time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 4, 24)),
    )

    plan = resolver.build_plan(request)

    assert plan.planning.universe_policy == "pool"
    assert plan.planning.unit_count == 6
    assert [unit.request_params for unit in plan.units] == [
        {"dm": "000001", "freq": "d", "adj_type": "n", "st": "20260424", "et": "20260424", "lt": "5000", "mc": "平安银行"},
        {"dm": "000001", "freq": "d", "adj_type": "f", "st": "20260424", "et": "20260424", "lt": "5000", "mc": "平安银行"},
        {"dm": "000001", "freq": "d", "adj_type": "b", "st": "20260424", "et": "20260424", "lt": "5000", "mc": "平安银行"},
        {"dm": "000002", "freq": "d", "adj_type": "n", "st": "20260424", "et": "20260424", "lt": "5000", "mc": "万科A"},
        {"dm": "000002", "freq": "d", "adj_type": "f", "st": "20260424", "et": "20260424", "lt": "5000", "mc": "万科A"},
        {"dm": "000002", "freq": "d", "adj_type": "b", "st": "20260424", "et": "20260424", "lt": "5000", "mc": "万科A"},
    ]
    assert [unit.trade_date for unit in plan.units] == [date(2026, 4, 24)] * 6
    assert {unit.progress_context["ts_code"] for unit in plan.units} == {"000001", "000002"}


def test_biying_equity_daily_explicit_code_keeps_missing_code_and_filters_adj_type(mocker) -> None:
    resolver = DatasetActionResolver(
        _mock_biying_stock_pool_session(
            mocker,
            [SimpleNamespace(dm="600000", mc="浦发银行")],
        )
    )
    request = DatasetActionRequest(
        dataset_key="biying_equity_daily",
        action="maintain",
        time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 4, 24)),
        filters={"ts_code": "600000.SH,000333.SZ", "adj_type": "b"},
    )

    plan = resolver.build_plan(request)

    assert plan.planning.unit_count == 2
    assert [unit.request_params for unit in plan.units] == [
        {"dm": "600000", "freq": "d", "adj_type": "b", "st": "20260424", "et": "20260424", "lt": "5000", "mc": "浦发银行"},
        {"dm": "000333", "freq": "d", "adj_type": "b", "st": "20260424", "et": "20260424", "lt": "5000"},
    ]
    assert {unit.progress_context["ts_code"] for unit in plan.units} == {"600000", "000333"}


def test_biying_moneyflow_range_request_chunks_windows_by_100_days(mocker) -> None:
    resolver = DatasetActionResolver(
        _mock_biying_stock_pool_session(
            mocker,
            [SimpleNamespace(dm="000001", mc="平安银行")],
        )
    )
    request = DatasetActionRequest(
        dataset_key="biying_moneyflow",
        action="maintain",
        time_input=DatasetTimeInput(mode="range", start_date=date(2026, 1, 1), end_date=date(2026, 4, 15)),
    )

    plan = resolver.build_plan(request)

    assert plan.planning.universe_policy == "pool"
    assert plan.planning.unit_count == 2
    assert [unit.request_params for unit in plan.units] == [
        {"dm": "000001", "st": "20260101", "et": "20260410", "mc": "平安银行"},
        {"dm": "000001", "st": "20260411", "et": "20260415", "mc": "平安银行"},
    ]
    assert [unit.trade_date for unit in plan.units] == [date(2026, 4, 10), date(2026, 4, 15)]


def test_biying_moneyflow_rejects_empty_stock_pool(mocker) -> None:
    resolver = DatasetActionResolver(_mock_biying_stock_pool_session(mocker, []))
    request = DatasetActionRequest(
        dataset_key="biying_moneyflow",
        action="maintain",
        time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 4, 24)),
    )

    with pytest.raises(IngestionPlanningError, match="Biying 股票池为空"):
        resolver.build_plan(request)


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


def test_dataset_action_resolver_builds_anns_d_point_and_range_units(mocker) -> None:
    resolver = DatasetActionResolver(mocker.Mock())

    point_plan = resolver.build_plan(
        DatasetActionRequest(
            dataset_key="anns_d",
            action="maintain",
            time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 4, 24)),
        )
    )
    range_plan = resolver.build_plan(
        DatasetActionRequest(
            dataset_key="anns_d",
            action="maintain",
            time_input=DatasetTimeInput(mode="range", start_date=date(2026, 4, 20), end_date=date(2026, 4, 24)),
            filters={"ts_code": "600000.sh"},
        )
    )

    assert point_plan.planning.unit_count == 1
    assert point_plan.units[0].request_params == {"start_date": "20260424", "end_date": "20260424"}
    assert range_plan.planning.unit_count == 1
    assert range_plan.units[0].request_params == {
        "start_date": "20260420",
        "end_date": "20260424",
        "ts_code": "600000.SH",
    }


@pytest.mark.parametrize("dataset_key", ("irm_qa_sh", "irm_qa_sz"))
def test_dataset_action_resolver_builds_irm_qa_point_and_range_units(mocker, dataset_key: str) -> None:
    resolver = DatasetActionResolver(mocker.Mock())

    point_plan = resolver.build_plan(
        DatasetActionRequest(
            dataset_key=dataset_key,
            action="maintain",
            time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 4, 24)),
        )
    )
    range_plan = resolver.build_plan(
        DatasetActionRequest(
            dataset_key=dataset_key,
            action="maintain",
            time_input=DatasetTimeInput(mode="range", start_date=date(2026, 4, 20), end_date=date(2026, 4, 24)),
            filters={"ts_code": "600000.sh"},
        )
    )

    assert point_plan.planning.unit_count == 1
    assert point_plan.units[0].request_params == {"trade_date": "20260424"}
    assert range_plan.planning.unit_count == 1
    assert range_plan.units[0].request_params == {
        "start_date": "20260420",
        "end_date": "20260424",
        "ts_code": "600000.SH",
    }


def test_dataset_action_resolver_builds_research_report_point_and_range_units(mocker) -> None:
    resolver = DatasetActionResolver(mocker.Mock())

    point_plan = resolver.build_plan(
        DatasetActionRequest(
            dataset_key="research_report",
            action="maintain",
            time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 1, 21)),
            filters={
                "report_type": ["个股研报", "行业研报"],
                "ts_code": "603659.sh",
                "inst_csname": "东吴证券",
                "ind_name": "电子",
            },
        )
    )
    range_plan = resolver.build_plan(
        DatasetActionRequest(
            dataset_key="research_report",
            action="maintain",
            time_input=DatasetTimeInput(mode="range", start_date=date(2026, 1, 1), end_date=date(2026, 1, 31)),
        )
    )

    assert point_plan.planning.unit_count == 2
    assert [unit.request_params for unit in point_plan.units] == [
        {
            "trade_date": "20260121",
            "report_type": "个股研报",
            "ts_code": "603659.SH",
            "inst_csname": "东吴证券",
            "ind_name": "电子",
        },
        {
            "trade_date": "20260121",
            "report_type": "行业研报",
            "ts_code": "603659.SH",
            "inst_csname": "东吴证券",
            "ind_name": "电子",
        },
    ]
    assert range_plan.planning.unit_count == 1
    assert range_plan.units[0].request_params == {"start_date": "20260101", "end_date": "20260131"}


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


def test_index_mins_defaults_to_all_freqs_and_active_pool(mocker) -> None:
    fake_dao = SimpleNamespace(
        index_series_active=SimpleNamespace(list_active_codes=mocker.Mock(return_value=["399001.SZ", "000001.SH"])),
        index_basic=SimpleNamespace(
            get_by_ts_code=mocker.Mock(
                side_effect=lambda code: SimpleNamespace(name={"000001.SH": "上证指数", "399001.SZ": "深证成指"}.get(code))
            )
        ),
    )
    mocker.patch("src.foundation.ingestion.unit_planner.DAOFactory", return_value=fake_dao)
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key="index_mins",
        action="maintain",
        time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 4, 30)),
    )

    plan = resolver.build_plan(request)

    assert plan.run_profile == "point_incremental"
    assert plan.planning.unit_count == 10
    assert plan.planning.pagination_policy == "offset_limit"
    assert plan.filters["freq"] == ["1min", "5min", "15min", "30min", "60min"]
    assert {unit.request_params["ts_code"] for unit in plan.units} == {"000001.SH", "399001.SZ"}
    assert {unit.request_params["freq"] for unit in plan.units} == {"1min", "5min", "15min", "30min", "60min"}
    assert all(unit.request_params["start_date"] == "2026-04-30 09:00:00" for unit in plan.units)
    assert all(unit.request_params["end_date"] == "2026-04-30 19:00:00" for unit in plan.units)
    assert any(unit.progress_context.get("index_name") == "上证指数" for unit in plan.units)
    fake_dao.index_series_active.list_active_codes.assert_called_once_with("index_mins")


def test_index_mins_rejects_explicit_code_outside_active_pool(mocker) -> None:
    fake_dao = SimpleNamespace(
        index_series_active=SimpleNamespace(list_active_codes=mocker.Mock(return_value=["000001.SH"])),
        index_basic=SimpleNamespace(get_by_ts_code=mocker.Mock()),
    )
    mocker.patch("src.foundation.ingestion.unit_planner.DAOFactory", return_value=fake_dao)
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key="index_mins",
        action="maintain",
        time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 4, 30)),
        filters={"ts_code": "399001.SZ", "freq": ["30min"]},
    )

    with pytest.raises(IngestionPlanningError, match="不在 index_mins 激活池"):
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


@pytest.mark.parametrize(
    ("dataset_key", "expected_api_params"),
    (
        ("stk_auction_o", {"trade_date": "20260424", "ts_code": "000001.SZ"}),
        ("stk_auction_c", {"trade_date": "20260424", "ts_code": "000001.SZ"}),
    ),
)
def test_dataset_action_resolver_builds_stock_auction_point_plan(
    mocker,
    dataset_key: str,
    expected_api_params: dict[str, str],
) -> None:
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key=dataset_key,
        action="maintain",
        time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 4, 24)),
        filters={"ts_code": "000001.sz"},
    )

    plan = resolver.build_plan(request)

    assert plan.run_profile == "point_incremental"
    assert plan.time_scope.mode == "point"
    assert plan.planning.unit_count == 1
    assert plan.units[0].request_params == expected_api_params
    assert plan.units[0].pagination_policy == "offset_limit"
    assert plan.units[0].page_limit == 10000


@pytest.mark.parametrize("dataset_key", ("stk_auction_o", "stk_auction_c"))
def test_dataset_action_resolver_builds_stock_auction_range_plan_by_open_days(mocker, dataset_key: str) -> None:
    fake_dao = SimpleNamespace(
        trade_calendar=SimpleNamespace(
            get_open_dates=mocker.Mock(return_value=[date(2026, 4, 22), date(2026, 4, 23), date(2026, 4, 24)])
        )
    )
    mocker.patch("src.foundation.ingestion.unit_planner.DAOFactory", return_value=fake_dao)
    resolver = DatasetActionResolver(mocker.Mock())
    request = DatasetActionRequest(
        dataset_key=dataset_key,
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
    assert all("start_date" not in unit.request_params for unit in plan.units)
    assert all("end_date" not in unit.request_params for unit in plan.units)
    fake_dao.trade_calendar.get_open_dates.assert_called_once_with("SSE", date(2026, 4, 21), date(2026, 4, 24))
    assert {unit.pagination_policy for unit in plan.units} == {"offset_limit"}
    assert {unit.page_limit for unit in plan.units} == {10000}


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
