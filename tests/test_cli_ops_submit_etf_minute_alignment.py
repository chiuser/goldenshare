from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from src.cli import app
from src.ops.services.etf_minute_history_alignment_submit_service import (
    EtfMinuteHistoryAlignmentSubmitError,
)


PLAN_HASH = "a" * 64


def _write_plan(path: Path) -> None:
    path.write_text(json.dumps({"plan_content_hash": PLAN_HASH}), encoding="utf-8")


def _patch_session_local(mocker):
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)
    return session


def _patch_service(mocker):
    confirmed_plan = mocker.Mock()
    result = mocker.Mock()
    result.render_summary.return_value = "submit summary"
    service = mocker.Mock()
    service.validate_plan_payload.return_value = confirmed_plan
    service.submit.return_value = result
    service_cls = mocker.patch(
        "src.cli.EtfMinuteHistoryAlignmentSubmitService",
        return_value=service,
    )
    return confirmed_plan, result, service, service_cls


def test_cli_requires_plan_hash_and_batch_size(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    _write_plan(plan)

    missing_plan = CliRunner().invoke(app, ["ops-submit-etf-minute-alignment"])
    missing_hash = CliRunner().invoke(
        app,
        ["ops-submit-etf-minute-alignment", "--plan", str(plan)],
    )
    missing_batch_size = CliRunner().invoke(
        app,
        [
            "ops-submit-etf-minute-alignment",
            "--plan",
            str(plan),
            "--confirm-plan-hash",
            PLAN_HASH,
        ],
    )

    assert missing_plan.exit_code == 2
    assert "--plan" in missing_plan.stderr
    assert missing_hash.exit_code == 2
    assert "--confirm-plan-hash" in missing_hash.stderr
    assert missing_batch_size.exit_code == 2
    assert "--batch-size" in missing_batch_size.stderr


def test_cli_validates_plan_before_opening_repeatable_read_transaction(
    mocker,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "plan.json"
    _write_plan(plan)
    session = _patch_session_local(mocker)
    confirmed_plan, _, service, service_cls = _patch_service(mocker)

    result = CliRunner().invoke(
        app,
        [
            "ops-submit-etf-minute-alignment",
            "--plan",
            str(plan),
            "--confirm-plan-hash",
            PLAN_HASH,
            "--batch-size",
            "10",
        ],
    )

    assert result.exit_code == 0
    assert result.stdout == "submit summary\n"
    service_cls.assert_called_once_with()
    service.validate_plan_payload.assert_called_once_with(
        {"plan_content_hash": PLAN_HASH},
        confirmed_plan_hash=PLAN_HASH,
    )
    statements = [str(call.args[0]) for call in session.execute.call_args_list]
    assert statements == [
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ",
        "SET LOCAL statement_timeout = '180s'",
    ]
    service.submit.assert_called_once_with(
        session,
        plan=confirmed_plan,
        batch_size=10,
    )


def test_cli_invalid_json_never_opens_database_session(mocker, tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text("{", encoding="utf-8")
    session_local = mocker.patch("src.cli.SessionLocal")
    service_cls = mocker.patch("src.cli.EtfMinuteHistoryAlignmentSubmitService")

    result = CliRunner().invoke(
        app,
        [
            "ops-submit-etf-minute-alignment",
            "--plan",
            str(plan),
            "--confirm-plan-hash",
            PLAN_HASH,
            "--batch-size",
            "10",
        ],
    )

    assert result.exit_code == 2
    assert "--plan" in result.stderr
    session_local.assert_not_called()
    service_cls.assert_not_called()


def test_cli_plan_validation_failure_never_opens_database_session(
    mocker,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "plan.json"
    _write_plan(plan)
    session_local = mocker.patch("src.cli.SessionLocal")
    _, _, service, _ = _patch_service(mocker)
    service.validate_plan_payload.side_effect = EtfMinuteHistoryAlignmentSubmitError(
        code="plan_content_hash_mismatch",
        message="alignment plan 内容已变化，请重新 preview",
    )

    result = CliRunner().invoke(
        app,
        [
            "ops-submit-etf-minute-alignment",
            "--plan",
            str(plan),
            "--confirm-plan-hash",
            PLAN_HASH,
            "--batch-size",
            "10",
        ],
    )

    assert result.exit_code == 2
    assert "plan_content_hash_mismatch" in result.stderr
    session_local.assert_not_called()


def test_cli_help_exposes_only_explicit_submit_controls() -> None:
    result = CliRunner().invoke(app, ["ops-submit-etf-minute-alignment", "--help"])

    assert result.exit_code == 0
    assert "--plan" in result.stdout
    assert "--confirm-plan-hash" in result.stdout
    assert "--batch-size" in result.stdout
    for forbidden in (
        "--alignment-start-date",
        "--alignment-end-date",
        "--as-of-date",
        "--ts-code",
        "--freq",
        "--apply",
        "--delete",
    ):
        assert forbidden not in result.stdout
