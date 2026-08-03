from __future__ import annotations

from sqlalchemy import event

from src.ops.services.schedule_automation_capability_audit_service import ScheduleAutomationCapabilityAuditService
from src.ops.services.schedule_automation_capability_resolver import ScheduleAutomationCapabilityResolver
from src.ops.services.schedule_probe_binding_service import ScheduleProbeBindingService


def _create_valid_margin_probe_schedule(ops_schedule_factory):
    return ops_schedule_factory(
        target_key="margin.maintain",
        display_name="融资融券汇总源站探测",
        schedule_type="cron",
        trigger_mode="probe",
        probe_config_json={
            "window_start": "09:00",
            "window_end": "09:30",
            "probe_interval_seconds": 300,
            "max_triggers_per_day": 1,
            "condition_kind": "remote_margin_ready",
        },
        params_json={"time_input": {"mode": "point"}, "filters": {}},
    )


def test_capability_audit_pages_whitelisted_reads_and_keeps_session_clean(
    db_session,
    ops_schedule_factory,
    probe_rule_factory,
) -> None:
    ops_schedule_factory(target_key="stock_basic.maintain", schedule_type="cron")
    margin_schedule = _create_valid_margin_probe_schedule(ops_schedule_factory)
    intent = ScheduleAutomationCapabilityResolver().validate_schedule(margin_schedule)
    template = ScheduleProbeBindingService.build_template(intent)
    assert template is not None
    probe_rule_factory(
        schedule_id=margin_schedule.id,
        dataset_key=template.dataset_key,
        source_key=template.source_key,
        window_start=template.window_start,
        window_end=template.window_end,
        probe_interval_seconds=template.probe_interval_seconds,
        probe_condition_json=template.probe_condition_json,
        on_success_action_json=template.on_success_action_json,
        max_triggers_per_day=template.max_triggers_per_day,
        timezone_name=template.timezone_name,
    )

    statements: list[str] = []

    def capture_statement(_connection, _cursor, statement, _parameters, _context, _executemany) -> None:  # type: ignore[no-untyped-def]
        statements.append(statement)

    event.listen(db_session.bind, "before_cursor_execute", capture_statement)
    try:
        report = ScheduleAutomationCapabilityAuditService().audit(db_session, batch_size=1, max_records=10)
    finally:
        event.remove(db_session.bind, "before_cursor_execute", capture_statement)

    assert report.passed is True
    assert report.schedule_count == 2
    assert report.probe_rule_count == 1
    assert report.schedule_pages == 2
    assert report.probe_rule_pages == 1
    assert statements
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)
    assert not db_session.new
    assert not db_session.dirty
    assert not db_session.deleted


def test_capability_audit_reports_invalid_schedule_missing_mismatched_and_orphan_rules(
    db_session,
    ops_schedule_factory,
    probe_rule_factory,
) -> None:
    _create_valid_margin_probe_schedule(ops_schedule_factory)
    invalid_source_schedule = _create_valid_margin_probe_schedule(ops_schedule_factory)
    invalid_source_schedule.probe_config_json = {
        **invalid_source_schedule.probe_config_json,
        "source_key": "biying",
    }
    db_session.commit()

    intent = ScheduleAutomationCapabilityResolver().validate_schedule(invalid_source_schedule)
    template = ScheduleProbeBindingService.build_template(intent)
    assert template is not None
    probe_rule_factory(
        schedule_id=invalid_source_schedule.id,
        dataset_key=template.dataset_key,
        source_key="biying",
        window_start=template.window_start,
        window_end=template.window_end,
        probe_interval_seconds=template.probe_interval_seconds,
        probe_condition_json=template.probe_condition_json,
        on_success_action_json={"action_type": "dataset_action", "action_key": "daily.maintain"},
        max_triggers_per_day=template.max_triggers_per_day,
        timezone_name=template.timezone_name,
    )
    workflow_schedule = ops_schedule_factory(
        target_type="workflow",
        target_key="daily_market_close_maintenance",
        schedule_type="cron",
        trigger_mode="probe",
        probe_config_json={"condition_kind": "remote_index_daily_ready"},
    )
    probe_rule_factory(
        schedule_id=workflow_schedule.id,
        dataset_key="index_daily",
        source_key="tushare",
    )
    probe_rule_factory(schedule_id=None, dataset_key="daily", source_key="tushare")

    report = ScheduleAutomationCapabilityAuditService().audit(db_session, batch_size=2, max_records=10)
    issue_codes = {item.code for item in report.issues}

    assert report.passed is False
    assert report.schedule_count == 3
    assert report.probe_rule_count == 3
    assert "probe_rule.missing" in issue_codes
    assert "source_key.operator_forbidden" in issue_codes
    assert "probe_rule.mismatch" in issue_codes
    assert "trigger_mode.forbidden" in issue_codes
    assert "probe_rule.target_forbidden" in issue_codes
    assert "probe_rule.orphan" in issue_codes
    forbidden_target = next(item for item in report.issues if item.probe_rule_id == 2)
    assert forbidden_target.code == "probe_rule.target_forbidden"
    assert forbidden_target.fields == ("parent_schedule.target_type",)
    mismatch = next(item for item in report.issues if item.probe_rule_id == 1 and item.code == "probe_rule.mismatch")
    assert set(mismatch.fields) == {"source_key", "on_success_action_json"}


def test_capability_audit_fails_closed_when_a_bounded_scan_has_more_rows(ops_schedule_factory, db_session) -> None:
    ops_schedule_factory(target_key="stock_basic.maintain", schedule_type="cron")
    ops_schedule_factory(target_key="daily.maintain", schedule_type="cron")

    report = ScheduleAutomationCapabilityAuditService().audit(db_session, batch_size=1, max_records=1)

    assert report.passed is False
    assert report.schedule_count == 1
    assert report.probe_rule_count == 0
    assert [item.code for item in report.issues] == ["audit.scan_limit_exceeded"]


def test_capability_audit_rejects_invalid_paging_bounds(db_session) -> None:
    service = ScheduleAutomationCapabilityAuditService()

    for batch_size, max_records in ((0, 1), (1, 0), (1_001, 1), (1, 1_001)):
        try:
            service.audit(db_session, batch_size=batch_size, max_records=max_records)
        except ValueError as exc:
            assert "必须在 1 到 1000 之间" in str(exc)
        else:
            raise AssertionError("无效的分页边界必须失败关闭")
