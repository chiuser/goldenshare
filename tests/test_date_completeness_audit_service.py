from __future__ import annotations

from datetime import date

import pytest

from src.ops.services.date_completeness_audit_service import ExpectedBucketPlanner, GapDetector


def test_expected_bucket_planner_builds_every_open_day_buckets() -> None:
    buckets = ExpectedBucketPlanner().plan(
        date_axis="trade_open_day",
        bucket_rule="every_open_day",
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 7),
        open_trade_dates=[
            date(2026, 4, 1),
            date(2026, 4, 2),
            date(2026, 4, 3),
            date(2026, 4, 7),
        ],
    )

    assert [bucket.value for bucket in buckets] == [
        date(2026, 4, 1),
        date(2026, 4, 2),
        date(2026, 4, 3),
        date(2026, 4, 7),
    ]
    assert {bucket.bucket_kind for bucket in buckets} == {"trade_date"}


def test_expected_bucket_planner_builds_week_and_month_last_open_day_buckets() -> None:
    open_dates = [
        date(2026, 4, 1),
        date(2026, 4, 2),
        date(2026, 4, 3),
        date(2026, 4, 7),
        date(2026, 4, 24),
        date(2026, 4, 28),
        date(2026, 5, 6),
    ]

    weekly = ExpectedBucketPlanner().plan(
        date_axis="trade_open_day",
        bucket_rule="week_last_open_day",
        start_date=date(2026, 4, 1),
        end_date=date(2026, 5, 6),
        open_trade_dates=open_dates,
    )
    monthly = ExpectedBucketPlanner().plan(
        date_axis="trade_open_day",
        bucket_rule="month_last_open_day",
        start_date=date(2026, 4, 1),
        end_date=date(2026, 5, 6),
        open_trade_dates=open_dates,
    )

    assert [bucket.value for bucket in weekly] == [
        date(2026, 4, 3),
        date(2026, 4, 7),
        date(2026, 4, 24),
        date(2026, 4, 28),
        date(2026, 5, 6),
    ]
    assert [bucket.value for bucket in monthly] == [date(2026, 4, 28), date(2026, 5, 6)]


def test_expected_bucket_planner_builds_natural_day_and_month_buckets() -> None:
    planner = ExpectedBucketPlanner()

    natural_days = planner.plan(
        date_axis="natural_day",
        bucket_rule="every_natural_day",
        start_date=date(2026, 4, 29),
        end_date=date(2026, 5, 1),
    )
    month_keys = planner.plan(
        date_axis="month_key",
        bucket_rule="every_natural_month",
        start_date=date(2026, 3, 15),
        end_date=date(2026, 5, 2),
    )
    month_windows = planner.plan(
        date_axis="month_window",
        bucket_rule="month_window_has_data",
        start_date=date(2026, 3, 15),
        end_date=date(2026, 5, 2),
    )

    assert [bucket.value for bucket in natural_days] == [date(2026, 4, 29), date(2026, 4, 30), date(2026, 5, 1)]
    assert [bucket.label for bucket in month_keys] == ["202603", "202604", "202605"]
    assert [bucket.bucket_kind for bucket in month_windows] == ["month_window", "month_window", "month_window"]


def test_gap_detector_compresses_missing_adjacent_expected_buckets() -> None:
    buckets = ExpectedBucketPlanner().plan(
        date_axis="trade_open_day",
        bucket_rule="every_open_day",
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 7),
        open_trade_dates=[
            date(2026, 4, 1),
            date(2026, 4, 2),
            date(2026, 4, 3),
            date(2026, 4, 7),
        ],
    )

    gaps = GapDetector().detect(
        expected_buckets=buckets,
        actual_bucket_values={date(2026, 4, 1), date(2026, 4, 7)},
    )

    assert len(gaps) == 1
    assert gaps[0].bucket_kind == "trade_date"
    assert gaps[0].range_start == date(2026, 4, 2)
    assert gaps[0].range_end == date(2026, 4, 3)
    assert gaps[0].missing_count == 2
    assert gaps[0].sample_values == ("2026-04-02", "2026-04-03")


def test_expected_bucket_planner_rejects_invalid_range() -> None:
    with pytest.raises(ValueError, match="开始日期不能晚于结束日期"):
        ExpectedBucketPlanner().plan(
            date_axis="natural_day",
            bucket_rule="every_natural_day",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 4, 1),
        )
