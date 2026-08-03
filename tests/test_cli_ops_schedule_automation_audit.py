from __future__ import annotations

from typer.testing import CliRunner

from src.cli import app


def _patch_session_local(mocker):
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)
    return session


def test_cli_schedule_automation_audit_uses_read_only_transaction_and_prints_report(mocker) -> None:
    session = _patch_session_local(mocker)
    report = mocker.Mock(passed=True)
    report.to_json.return_value = '{"passed": true}'
    service = mocker.Mock()
    service.audit.return_value = report
    service_cls = mocker.patch("src.cli.ScheduleAutomationCapabilityAuditService", return_value=service)

    result = CliRunner().invoke(
        app,
        [
            "ops-audit-schedule-automation-capability",
            "--batch-size",
            "25",
            "--max-records",
            "50",
            "--expected-schedule-count",
            "28",
            "--expected-probe-rule-count",
            "6",
        ],
    )

    assert result.exit_code == 0
    assert result.stdout == '{"passed": true}\n'
    assert "REPEATABLE READ, READ ONLY" in str(session.execute.call_args.args[0])
    session.rollback.assert_called_once_with()
    session.commit.assert_not_called()
    service_cls.assert_called_once_with()
    service.audit.assert_called_once_with(
        session,
        batch_size=25,
        max_records=50,
        expected_schedule_count=28,
        expected_probe_rule_count=6,
    )


def test_cli_schedule_automation_audit_fails_when_report_has_mismatch(mocker) -> None:
    session = _patch_session_local(mocker)
    report = mocker.Mock(passed=False)
    report.to_json.return_value = '{"passed": false}'
    service = mocker.Mock()
    service.audit.return_value = report
    mocker.patch("src.cli.ScheduleAutomationCapabilityAuditService", return_value=service)

    result = CliRunner().invoke(app, ["ops-audit-schedule-automation-capability"])

    assert result.exit_code == 1
    assert result.stdout == '{"passed": false}\n'
    session.rollback.assert_called_once_with()
    session.commit.assert_not_called()
