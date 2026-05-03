from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.app.exceptions import WebAppError
from src.ops.services.schedule_planner import compute_next_run_at, preview_schedule_runs


def test_monthly_last_day_policy_computes_natural_month_end_in_timezone() -> None:
    next_run = compute_next_run_at(
        schedule_type="cron",
        timezone_name="Asia/Shanghai",
        cron_expr="0 19 * * *",
        calendar_policy="monthly_last_day",
        after=datetime(2026, 4, 20, 2, 0, tzinfo=timezone.utc),
    )

    assert next_run == datetime(2026, 4, 30, 11, 0, tzinfo=timezone.utc)


def test_monthly_last_day_policy_moves_to_next_month_after_current_month_run() -> None:
    next_run = compute_next_run_at(
        schedule_type="cron",
        timezone_name="Asia/Shanghai",
        cron_expr="0 19 * * *",
        calendar_policy="monthly_last_day",
        after=datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc),
    )

    assert next_run == datetime(2026, 5, 31, 11, 0, tzinfo=timezone.utc)


def test_monthly_last_day_preview_returns_month_ends() -> None:
    runs = preview_schedule_runs(
        schedule_type="cron",
        timezone_name="Asia/Shanghai",
        cron_expr="30 18 * * *",
        calendar_policy="monthly_last_day",
        after=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
        count=3,
    )

    assert runs == [
        datetime(2026, 1, 31, 10, 30, tzinfo=timezone.utc),
        datetime(2026, 2, 28, 10, 30, tzinfo=timezone.utc),
        datetime(2026, 3, 31, 10, 30, tzinfo=timezone.utc),
    ]


def test_monthly_last_day_policy_rejects_multiple_execution_times() -> None:
    with pytest.raises(WebAppError, match="每月最后一天策略必须使用单一执行时间"):
        compute_next_run_at(
            schedule_type="cron",
            timezone_name="Asia/Shanghai",
            cron_expr="0,30 19 * * *",
            calendar_policy="monthly_last_day",
            after=datetime(2026, 4, 20, 2, 0, tzinfo=timezone.utc),
        )
