"""Automatic intent, source units and resume identities without external resources."""

from datetime import date, datetime, timezone
from unittest.mock import Mock

import pytest

from src.app.exceptions import WebAppError
from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion.execution_plan import (
    DatasetActionRequest,
    DatasetTimeInput,
)
from src.foundation.ingestion.resolver import DatasetActionResolver
from src.ops.schemas.catalog import CalendarPolicyCapabilityResponse
from src.ops.services.dataset_schedule_time_policy_resolver import (
    DatasetScheduleTimePolicyResolver,
)
from src.ops.services.operations_schedule_service import OperationsScheduleService
from src.ops.services.schedule_automation_capability_resolver import (
    ScheduleAutomationCapabilityResolver,
)
from src.ops.services.schedule_planner import compute_next_run_at
from src.ops.services.task_run_service import TaskRunCommandService

POLICY = "trigger_day_forward_range"


def resolve(scheduled, params=None, dataset="anns_d"):
    return TaskRunCommandService()._resolve_dataset_action_schedule_time_input(
        session=None,
        definition=get_dataset_definition(dataset),
        target_key=f"{dataset}.maintain",
        params_json=params or {},
        calendar_policy=POLICY,
        scheduled_at=scheduled,
        timezone_name="UTC",
    )


@pytest.mark.parametrize(
    "scheduled,start,end",
    [
        ("2026-10-12T00:00:00+00:00", "2026-10-12", "2026-10-13"),
        ("2026-10-11T16:00:00+00:00", "2026-10-12", "2026-10-13"),
        ("2026-01-31T11:00:00+00:00", "2026-01-31", "2026-02-01"),
        ("2026-12-31T11:00:00+00:00", "2026-12-31", "2027-01-01"),
    ],
)
def test_shanghai_scheduled_day_closed_two_day_window(scheduled, start, end):
    assert resolve(datetime.fromisoformat(scheduled)) == dict(
        mode="range", start_date=start, end_date=end
    )


@pytest.mark.parametrize("scheduled", [None, datetime(2026, 10, 12)])
def test_no_machine_clock_fallback(scheduled):
    with pytest.raises(WebAppError, match="含时区"):
        resolve(scheduled)


@pytest.mark.parametrize(
    "params",
    [
        {"trade_date": "2026-10-12"},
        {
            "time_input": {
                "mode": "range",
                "start_date": "2026-10-12",
                "end_date": "2026-10-13",
            }
        },
    ],
)
def test_dynamic_range_cannot_mix_fixed_dates(params):
    with pytest.raises(WebAppError, match="固定"):
        resolve(datetime(2026, 10, 12, tzinfo=timezone.utc), params)


def test_policy_only_declared_for_announcements_and_catalog_schema():
    definition = get_dataset_definition("anns_d")
    rules = DatasetScheduleTimePolicyResolver().resolve(
        definition=definition, action="maintain"
    )
    assert len(rules) == 1 and rules[0].policy == POLICY
    payload = CalendarPolicyCapabilityResponse(
        **{
            name: getattr(rules[0], name)
            for name in CalendarPolicyCapabilityResponse.model_fields
        }
    )
    assert payload.generated_time_mode == "range"
    assert payload.generated_time_field == "start_date_end_date"
    assert definition.date_model.bucket_rule == "not_applicable"
    assert definition.capabilities.get_action("maintain").supported_time_modes == (
        "point",
        "range",
    )
    with pytest.raises(WebAppError, match="未声明"):
        resolve(datetime(2026, 10, 12, tzinfo=timezone.utc), dataset="daily")


def validate(
    schedule_type="cron", policy=POLICY, params=None, cron="0 8 * * *", dataset="anns_d"
):
    OperationsScheduleService._validate_calendar_policy(
        target_type="dataset_action",
        target_key=f"{dataset}.maintain",
        schedule_type=schedule_type,
        cron_expr=cron,
        calendar_policy=policy,
        params_json=params or {},
    )


def test_cron_required_policy_but_fixed_once_preserved():
    validate()
    with pytest.raises(WebAppError, match="必须"):
        validate(policy=None)
    with pytest.raises(WebAppError, match="周期类型"):
        validate(cron="0 8 * * 1")
    with pytest.raises(WebAppError, match="固定"):
        validate(params={"trade_date": "2026-10-12"})
    validate(
        schedule_type="once",
        policy=None,
        cron=None,
        params={"trade_date": "2026-10-12"},
    )
    cap = ScheduleAutomationCapabilityResolver().resolve(
        target_type="dataset_action", target_key="anns_d.maintain"
    )
    assert set(cap.trigger_options[0].allowed_schedule_types) == {"once", "cron"}
    service = ScheduleAutomationCapabilityResolver()
    service._validate_schedule_policy_contract(
        schedule=Mock(calendar_policy=None, schedule_type="once", params_json={}),
        capability=cap,
    )
    with pytest.raises(WebAppError, match="必须"):
        service._validate_schedule_policy_contract(
            schedule=Mock(calendar_policy=None, schedule_type="cron", params_json={}),
            capability=cap,
        )


def test_daily_cron_occurrence_unchanged():
    assert compute_next_run_at(
        schedule_type="cron",
        timezone_name="Asia/Shanghai",
        after=datetime(2026, 10, 11, 0, tzinfo=timezone.utc),
        cron_expr="0 8 * * *",
        calendar_policy=POLICY,
    ) == datetime(2026, 10, 12, 0, tzinfo=timezone.utc)


def test_two_independent_daily_source_units_and_frozen_midnight_resume():
    resolver = DatasetActionResolver(Mock())
    request = DatasetActionRequest(
        dataset_key="anns_d",
        action="maintain",
        time_input=DatasetTimeInput(
            mode="range", start_date=date(2026, 10, 12), end_date=date(2026, 10, 13)
        ),
    )
    first = resolver.build_plan(request)
    assert [u.trade_date for u in first.units] == [
        date(2026, 10, 12),
        date(2026, 10, 13),
    ]
    assert [u.request_params for u in first.units] == [
        {"start_date": "20261012", "end_date": "20261012"},
        {"start_date": "20261013", "end_date": "20261013"},
    ]
    again = resolver.build_plan(request)
    assert (
        again.execution_context["execution_token"]
        != first.execution_context["execution_token"]
    )
    resumed = resolver.build_plan(
        DatasetActionRequest(
            dataset_key="anns_d",
            action="maintain",
            time_input=request.time_input,
            execution_context=first.execution_context,
        )
    )
    assert resumed.execution_context == first.execution_context
    assert [u.request_params for u in resumed.units] == [
        u.request_params for u in first.units
    ]
