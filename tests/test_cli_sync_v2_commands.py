from __future__ import annotations

from datetime import date

from typer.testing import CliRunner

from src.cli import app
from src.foundation.services.sync_v2.linter import ContractLintIssue, ContractLintReport
from src.ops.services.operations_dataset_reconcile_service import (
    DatasetReconcileDailyDiff,
    DatasetReconcileReport,
)


def test_cli_sync_v2_lint_contracts_passes(mocker) -> None:
    mocker.patch(
        "src.cli.lint_all_sync_v2_contracts",
        return_value=ContractLintReport(passed=True, issues=[]),
    )

    result = CliRunner().invoke(app, ["sync-v2-lint-contracts"])

    assert result.exit_code == 0
    assert "sync-v2-lint-contracts: passed" in result.stdout


def test_cli_sync_v2_lint_contracts_fails_with_issues(mocker) -> None:
    mocker.patch(
        "src.cli.lint_all_sync_v2_contracts",
        return_value=ContractLintReport(
            passed=False,
            issues=[ContractLintIssue(dataset_key="margin", code="fanout_defaults_missing", message="missing defaults")],
        ),
    )

    result = CliRunner().invoke(app, ["sync-v2-lint-contracts"])

    assert result.exit_code == 1
    assert "sync-v2-lint-contracts: failed issues=1" in result.stdout
    assert "dataset=margin" in result.stdout


def test_cli_reconcile_dataset_prints_summary(mocker) -> None:
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)

    mocker.patch(
        "src.cli.DatasetReconcileService",
        return_value=mocker.Mock(
            run=mocker.Mock(
                return_value=DatasetReconcileReport(
                    dataset_key="trade_cal",
                    start_date=date(2026, 4, 1),
                    end_date=date(2026, 4, 2),
                    raw_rows=10,
                    serving_rows=9,
                    daily_diffs=[
                        DatasetReconcileDailyDiff(
                            trade_date=date(2026, 4, 2),
                            raw_rows=5,
                            serving_rows=4,
                            diff=1,
                        )
                    ],
                )
            )
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "reconcile-dataset",
            "--dataset",
            "trade_cal",
            "--start-date",
            "2026-04-01",
            "--end-date",
            "2026-04-02",
            "--sample-limit",
            "1",
        ],
    )

    assert result.exit_code == 0
    assert "reconcile-dataset summary" in result.stdout
    assert "dataset=trade_cal" in result.stdout
    assert "abs_diff=1" in result.stdout
    assert "[daily_diff] samples=1" in result.stdout


def test_cli_reconcile_dataset_honors_abs_diff_threshold(mocker) -> None:
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)

    mocker.patch(
        "src.cli.DatasetReconcileService",
        return_value=mocker.Mock(
            run=mocker.Mock(
                return_value=DatasetReconcileReport(
                    dataset_key="trade_cal",
                    start_date=date(2026, 4, 1),
                    end_date=date(2026, 4, 2),
                    raw_rows=20,
                    serving_rows=10,
                    daily_diffs=[],
                )
            )
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "reconcile-dataset",
            "--dataset",
            "trade_cal",
            "--abs-diff-threshold",
            "5",
            "--sample-limit",
            "0",
        ],
    )

    assert result.exit_code == 1
    assert "reconcile-dataset gate failed" in result.stdout
