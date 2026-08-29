from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from src.cli import app
from src.ops.services.etf_minute_history_alignment_plan_service import (
    EtfMinuteHistoryAlignmentPlanError,
)


def _patch_session_local(mocker):
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)
    return session


def _patch_service(mocker, *, summary: str = "preview summary", payload: dict | None = None):
    plan = mocker.Mock()
    plan.render_summary.return_value = summary
    plan.to_json.return_value = json.dumps(payload or {"plan_id": "plan-1"})
    service = mocker.Mock()
    service.build_plan.return_value = plan
    service_cls = mocker.patch(
        "src.cli.EtfMinuteHistoryAlignmentPlanService",
        return_value=service,
    )
    return plan, service, service_cls


def test_cli_requires_alignment_start_and_end_dates() -> None:
    missing_start = CliRunner().invoke(app, ["ops-preview-etf-minute-alignment"])
    missing_end = CliRunner().invoke(
        app,
        [
            "ops-preview-etf-minute-alignment",
            "--alignment-start-date",
            "2026-01-01",
        ],
    )

    assert missing_start.exit_code == 2
    assert "--alignment-start-date" in missing_start.stderr
    assert missing_end.exit_code == 2
    assert "--alignment-end-date" in missing_end.stderr


def test_cli_rejects_invalid_alignment_start_date_before_opening_session(mocker) -> None:
    session_local = mocker.patch("src.cli.SessionLocal")

    result = CliRunner().invoke(
        app,
        [
            "ops-preview-etf-minute-alignment",
            "--alignment-start-date",
            "2026/01/01",
            "--alignment-end-date",
            "2026-08-28",
        ],
    )

    assert result.exit_code == 2
    assert "--alignment-start-date" in result.stderr
    assert "YYYY-MM-DD" in result.stderr
    session_local.assert_not_called()


def test_cli_rejects_invalid_alignment_end_date_before_opening_session(mocker) -> None:
    session_local = mocker.patch("src.cli.SessionLocal")

    result = CliRunner().invoke(
        app,
        [
            "ops-preview-etf-minute-alignment",
            "--alignment-start-date",
            "2026-01-01",
            "--alignment-end-date",
            "2026/08/28",
        ],
    )

    assert result.exit_code == 2
    assert "YYYY-MM-DD" in result.stderr
    session_local.assert_not_called()


def test_cli_prints_summary_after_read_only_transaction_rollback(mocker) -> None:
    session = _patch_session_local(mocker)
    plan, service, service_cls = _patch_service(mocker)
    plan.render_summary.side_effect = lambda: (
        "preview summary" if session.rollback.called else (_ for _ in ()).throw(AssertionError())
    )

    result = CliRunner().invoke(
        app,
        [
            "ops-preview-etf-minute-alignment",
            "--alignment-start-date",
            "2026-01-01",
            "--alignment-end-date",
            "2026-08-28",
        ],
    )

    assert result.exit_code == 0
    assert result.stdout == "preview summary\n"
    statements = [str(call.args[0]) for call in session.execute.call_args_list]
    assert statements == [
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY",
        "SET LOCAL statement_timeout = '180s'",
    ]
    session.rollback.assert_called_once_with()
    session.commit.assert_not_called()
    session.flush.assert_not_called()
    service_cls.assert_called_once_with()
    service.build_plan.assert_called_once()
    assert (
        service.build_plan.call_args.kwargs["alignment_start_date"].isoformat()
        == "2026-01-01"
    )
    assert service.build_plan.call_args.kwargs["alignment_end_date"].isoformat() == "2026-08-28"


def test_cli_writes_complete_json_atomically_after_rollback(mocker, tmp_path: Path) -> None:
    session = _patch_session_local(mocker)
    payload = {"plan_id": "plan-1", "actions": []}
    plan, _, _ = _patch_service(mocker, payload=payload)
    output = tmp_path / "nested" / "alignment-plan.json"
    plan.to_json.side_effect = lambda: (
        json.dumps(payload)
        if session.rollback.called
        else (_ for _ in ()).throw(AssertionError())
    )

    result = CliRunner().invoke(
        app,
        [
            "ops-preview-etf-minute-alignment",
            "--alignment-start-date",
            "2026-01-01",
            "--alignment-end-date",
            "2026-08-28",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    assert json.loads(output.read_text(encoding="utf-8")) == payload
    assert "preview summary" in result.stdout
    assert f"written={output}" in result.stdout
    assert list(output.parent.glob("*.tmp")) == []


def test_cli_service_failure_rolls_back_and_does_not_create_output(mocker, tmp_path: Path) -> None:
    session = _patch_session_local(mocker)
    service = mocker.Mock()
    service.build_plan.side_effect = EtfMinuteHistoryAlignmentPlanError(
        code="alignment_end_date_not_open",
        message="对齐截止日不是 SSE 开市日",
    )
    mocker.patch(
        "src.cli.EtfMinuteHistoryAlignmentPlanService",
        return_value=service,
    )
    output = tmp_path / "alignment-plan.json"

    result = CliRunner().invoke(
        app,
        [
            "ops-preview-etf-minute-alignment",
            "--alignment-start-date",
            "2026-01-01",
            "--alignment-end-date",
            "2026-08-28",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 2
    assert "alignment_end_date_not_open" in result.stderr
    session.rollback.assert_called_once_with()
    assert not output.exists()


def test_cli_output_replace_failure_leaves_no_partial_file(mocker, tmp_path: Path) -> None:
    session = _patch_session_local(mocker)
    _patch_service(mocker)
    mocker.patch(
        "src.cli_parts.ops_handlers.os.replace",
        side_effect=OSError("replace failed"),
    )
    output = tmp_path / "alignment-plan.json"

    result = CliRunner().invoke(
        app,
        [
            "ops-preview-etf-minute-alignment",
            "--alignment-start-date",
            "2026-01-01",
            "--alignment-end-date",
            "2026-08-28",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 1
    session.rollback.assert_called_once_with()
    assert not output.exists()
    assert list(tmp_path.glob("*.tmp")) == []


def test_cli_generic_service_exception_rolls_back_without_fallback(mocker) -> None:
    session = _patch_session_local(mocker)
    service = mocker.Mock()
    service.build_plan.side_effect = RuntimeError("raw query failed")
    mocker.patch(
        "src.cli.EtfMinuteHistoryAlignmentPlanService",
        return_value=service,
    )

    result = CliRunner().invoke(
        app,
        [
            "ops-preview-etf-minute-alignment",
            "--alignment-start-date",
            "2026-01-01",
            "--alignment-end-date",
            "2026-08-28",
        ],
    )

    assert result.exit_code == 1
    session.rollback.assert_called_once_with()
    session.commit.assert_not_called()


def test_cli_help_exposes_only_fixed_preview_inputs() -> None:
    result = CliRunner().invoke(
        app,
        ["ops-preview-etf-minute-alignment", "--help"],
    )

    assert result.exit_code == 0
    assert "--alignment-start-date" in result.stdout
    assert "--alignment-end-date" in result.stdout
    assert "--output" in result.stdout
    for forbidden in (
        "--as-of-date",
        "--ts-code",
        "--freq",
        "--batch-size",
        "--submit",
        "--apply",
    ):
        assert forbidden not in result.stdout


def test_cli_no_longer_registers_etf_minute_alignment_submit_command() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "ops-preview-etf-minute-alignment" in result.stdout
    assert "ops-submit-etf-minute-alignment" not in result.stdout
