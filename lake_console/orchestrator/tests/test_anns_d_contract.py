import math
from datetime import date

import pytest

from orchestrator.defs.anns_d_contract import (
    ANNOUNCEMENT_FIELDS,
    AnnouncementError,
    announcement_dates,
    normalize_announcement_rows,
)
from orchestrator.defs.run_contracts.anns_d import AnnouncementPolicy
from tests.anns_d_test_support import source_row


def test_original_fields_and_transport_null():
    assert normalize_announcement_rows(
        [source_row(name=" 名称 ", url=float("nan"))], sdk=True, day="2023-06-09"
    )[0] == source_row(name=" 名称 ")
    for value in ("", " ", "HTTP://Example/a.pdf"):
        assert normalize_announcement_rows([source_row(url=value)])[0]["url"] == value


@pytest.mark.parametrize(
    "values",
    [
        {"url": 1.5},
        {"rec_time": {}},
        {"ann_date": None},
        {"ann_date": "2023-06-09"},
        {"ann_date": "20230230"},
        {"url": math.inf},
    ],
)
def test_invalid_source_types_and_dates(values):
    with pytest.raises(AnnouncementError):
        normalize_announcement_rows([source_row(**values)], sdk=True)


def test_keys_schema_and_partition():
    with pytest.raises(AnnouncementError):
        normalize_announcement_rows([source_row(system_field="bad")])
    with pytest.raises(AnnouncementError):
        normalize_announcement_rows([], columns=())
    assert normalize_announcement_rows([], columns=ANNOUNCEMENT_FIELDS) == []
    with pytest.raises(AnnouncementError):
        normalize_announcement_rows([source_row()], day="2023-06-10")


def test_natural_calendar_and_closed_range():
    assert announcement_dates("2023-06-09", "2023-06-11", today=date(2023, 6, 12)) == (
        "2023-06-09",
        "2023-06-10",
        "2023-06-11",
    )
    for start, end in [
        ("2023-06-11", "2023-06-09"),
        ("2023-06-11", "2023-06-12"),
        ("2019-12-31", "2020-01-01"),
    ]:
        with pytest.raises(AnnouncementError):
            announcement_dates(start, end, today=date(2023, 6, 12))


@pytest.mark.parametrize(
    "options",
    [
        {"interval_seconds": float("nan")},
        {"interval_seconds": -1},
        {"page_size": 6000},
        {"call_timeout": 0},
        {"max_window_requests": 0},
    ],
)
def test_policy_rejects_invalid_defaults(options):
    with pytest.raises(ValueError):
        AnnouncementPolicy(**options)


def test_pandas_missing_sentinels_restore_null_without_converting_values():
    from pandas import NA, NaT

    assert normalize_announcement_rows(
        [source_row(url=NA, rec_time=NaT)], sdk=True
    ) == [source_row()]


@pytest.mark.parametrize("options", [{"prod_fetch_rows": 1.5}, {"max_attempts": True}])
def test_integer_budgets_cannot_be_fractional(options):
    with pytest.raises(ValueError):
        AnnouncementPolicy(**options)
