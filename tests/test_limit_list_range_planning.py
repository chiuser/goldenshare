from __future__ import annotations

from datetime import date
from itertools import product
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.foundation.ingestion import DatasetActionRequest, DatasetActionResolver, DatasetTimeInput
from src.foundation.ingestion.errors import IngestionValidationError
from src.foundation.models.core.trade_calendar import TradeCalendar


@pytest.fixture
def resolver():
    # Real producer schema. All five SSE flags were checked in production on
    # 2026-10-25, in a read-only, five-row query recorded in design section 9.
    # Using a real DAO matters: an unconditional mocked date list hid this bug.
    engine = create_engine("sqlite:///:memory:").execution_options(
        schema_translate_map={"core_serving": None}
    )
    TradeCalendar.__table__.create(engine)
    with Session(engine) as session:
        session.add_all(
            TradeCalendar(exchange="SSE", trade_date=date(2026, 10, day), is_open=is_open)
            for day, is_open in ((21, True), (22, True), (23, True), (24, False), (25, False))
        )
        session.commit()
        value = DatasetActionResolver(session)
        value.unit_planner.settings = SimpleNamespace(default_exchange="SSE")
        yield value
    engine.dispose()


def _range_request(*, dataset_key="limit_list_d", filters=None, start_day=21, end_day=25):
    return DatasetActionRequest(
        dataset_key=dataset_key,
        action="maintain",
        time_input=DatasetTimeInput(
            mode="range", start_date=date(2026, 10, start_day), end_date=date(2026, 10, end_day)
        ),
        filters={} if filters is None else filters,
    )


@pytest.mark.parametrize(
    "filters",
    ({}, {"limit_type": ["U", "D", "Z"], "exchange": ["SH", "SZ", "BJ"]}),
    ids=("default-filters", "task-16801-filters"),
)
def test_limit_list_range_expands_real_sse_calendar_and_all_source_combinations(resolver, filters):
    plan = resolver.build_plan(_range_request(filters=filters))

    # Dates: production calendar. Source enum values/format: local doc_id 298.
    # Expected tuples are independent of the planner's enum/date helpers.
    expected = set(
        product(("20261021", "20261022", "20261023"), ("U", "D", "Z"), ("SH", "SZ", "BJ"))
    )
    actual = {
        (u.request_params["trade_date"], u.request_params["limit_type"], u.request_params["exchange"])
        for u in plan.units
    }
    assert plan.planning.unit_count == len(plan.units) == 27
    assert actual == expected
    assert len({u.unit_id for u in plan.units}) == 27
    assert {u.trade_date for u in plan.units} == {
        date(2026, 10, 21), date(2026, 10, 22), date(2026, 10, 23)
    }
    assert all(set(u.request_params) == {"trade_date", "limit_type", "exchange"} for u in plan.units)
    assert all(u.pagination_policy == "offset_limit" and u.page_limit == 2500 for u in plan.units)


@pytest.mark.parametrize("selected_exchange", (["SZ"], "SZ"))
def test_limit_list_range_preserves_source_subset_without_using_it_as_calendar(resolver, selected_exchange):
    plan = resolver.build_plan(
        _range_request(filters={"limit_type": ["U"], "exchange": selected_exchange})
    )

    assert plan.planning.unit_count == 3
    assert [u.request_params for u in plan.units] == [
        {"trade_date": "20261021", "limit_type": "U", "exchange": "SZ"},
        {"trade_date": "20261022", "limit_type": "U", "exchange": "SZ"},
        {"trade_date": "20261023", "limit_type": "U", "exchange": "SZ"},
    ]


def test_limit_list_point_keeps_nine_units_without_calendar_lookup(resolver, monkeypatch):
    def unexpected_calendar_read(*args):
        raise AssertionError("point input must not expand a calendar range")

    monkeypatch.setattr(resolver.unit_planner.dao.trade_calendar, "get_open_dates", unexpected_calendar_read)
    plan = resolver.build_plan(
        DatasetActionRequest(
            dataset_key="limit_list_d",
            action="maintain",
            time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 10, 22)),
        )
    )

    assert plan.planning.unit_count == 9
    assert {
        (u.request_params["trade_date"], u.request_params["limit_type"], u.request_params["exchange"])
        for u in plan.units
    } == set(product(("20261022",), ("U", "D", "Z"), ("SH", "SZ", "BJ")))


def test_limit_list_closed_day_range_remains_a_valid_empty_plan(resolver):
    plan = resolver.build_plan(_range_request(start_day=24, end_day=25))

    assert plan.planning.unit_count == 0
    assert plan.units == ()


def test_limit_list_source_filter_still_rejects_calendar_exchange_name(resolver):
    with pytest.raises(IngestionValidationError) as exc_info:
        resolver.build_plan(_range_request(filters={"exchange": "SSE"}))

    assert exc_info.value.structured_error.error_code == "invalid_enum"


def test_range_uses_configured_calendar_instead_of_hardcoding_sse(resolver):
    # Synthetic independent calendar explicitly tests the existing setting;
    # it is not a claim that production has this additional calendar.
    resolver.session.add(TradeCalendar(exchange="TEST", trade_date=date(2026, 10, 22), is_open=True))
    resolver.session.commit()
    resolver.unit_planner.settings = SimpleNamespace(default_exchange="TEST")

    plan = resolver.build_plan(_range_request(filters={"limit_type": "U", "exchange": "SH"}))

    assert [u.request_params for u in plan.units] == [
        {"trade_date": "20261022", "limit_type": "U", "exchange": "SH"}
    ]


@pytest.mark.parametrize(
    ("dataset_key", "expected_dates"),
    (
        ("daily", [date(2026, 10, 21), date(2026, 10, 22), date(2026, 10, 23)]),
        ("index_weekly", [date(2026, 10, 23)]),
    ),
)
def test_other_trade_day_ranges_keep_existing_date_rules(resolver, dataset_key, expected_dates):
    plan = resolver.build_plan(_range_request(dataset_key=dataset_key))

    assert [u.trade_date for u in plan.units] == expected_dates
