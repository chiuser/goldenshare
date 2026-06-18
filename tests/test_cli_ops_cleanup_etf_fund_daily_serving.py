from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from src.cli import app


def _patch_session_local(mocker):
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)
    return session


def test_cli_ops_cleanup_etf_fund_daily_serving_dry_run(mocker) -> None:
    session = _patch_session_local(mocker)
    service = mocker.Mock()
    service.run.return_value = mocker.Mock(
        output_path="reports/outside.csv",
        confirm_report_path=None,
        outside_code_count=2,
        outside_row_count=3,
        deleted_count=0,
        post_outside_row_count=3,
        raw_row_count_before=10,
        raw_row_count_after=10,
        active_task_run_count=0,
    )
    mocker.patch("src.cli.EtfFundDailyServingCleanupService", return_value=service)

    result = CliRunner().invoke(
        app,
        [
            "ops-cleanup-etf-fund-daily-serving",
            "--output",
            "reports/outside.csv",
        ],
    )

    assert result.exit_code == 0
    assert "ops-cleanup-etf-fund-daily-serving [dry-run]" in result.stdout
    assert "outside_codes=2" in result.stdout
    service.run.assert_called_once_with(
        session,
        dry_run=True,
        output_path=Path("reports/outside.csv"),
        confirm_report_path=None,
    )


def test_cli_ops_cleanup_etf_fund_daily_serving_apply(mocker) -> None:
    session = _patch_session_local(mocker)
    service = mocker.Mock()
    service.run.return_value = mocker.Mock(
        output_path=None,
        confirm_report_path="reports/outside.csv",
        outside_code_count=2,
        outside_row_count=0,
        deleted_count=3,
        post_outside_row_count=0,
        raw_row_count_before=10,
        raw_row_count_after=10,
        active_task_run_count=0,
    )
    mocker.patch("src.cli.EtfFundDailyServingCleanupService", return_value=service)

    result = CliRunner().invoke(
        app,
        [
            "ops-cleanup-etf-fund-daily-serving",
            "--apply",
            "--confirm-report",
            "reports/outside.csv",
        ],
    )

    assert result.exit_code == 0
    assert "ops-cleanup-etf-fund-daily-serving [apply]" in result.stdout
    assert "deleted=3" in result.stdout
    service.run.assert_called_once_with(
        session,
        dry_run=False,
        output_path=None,
        confirm_report_path=Path("reports/outside.csv"),
    )
