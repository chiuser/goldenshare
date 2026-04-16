from __future__ import annotations

from datetime import date

from typer.testing import CliRunner

from src.cli import app
from src.operations.services.moneyflow_reconcile_service import MoneyflowDiffSample, MoneyflowReconcileReport


def _build_report(comparable_diff: int) -> MoneyflowReconcileReport:
    return MoneyflowReconcileReport(
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 10),
        total_union=4,
        comparable=2,
        only_tushare=1,
        only_biying=1,
        comparable_diff=comparable_diff,
        direction_mismatch=1 if comparable_diff else 0,
        samples={
            "only_tushare": [
                MoneyflowDiffSample(
                    ts_code="000003.SZ",
                    trade_date=date(2026, 4, 10),
                    diff_type="only_tushare",
                    field=None,
                    tushare_value=None,
                    biying_value=None,
                    abs_diff=None,
                    rel_diff=None,
                    note="仅 Tushare 存在",
                )
            ],
            "only_biying": [],
            "comparable_diff": [],
        },
    )


def test_cli_reconcile_moneyflow_success(mocker) -> None:
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)

    service = mocker.Mock()
    service.run.return_value = _build_report(comparable_diff=0)
    mocker.patch("src.cli.MoneyflowReconcileService", return_value=service)

    result = CliRunner().invoke(
        app,
        [
            "reconcile-moneyflow",
            "--sample-limit",
            "0",
            "--abs-tol",
            "1",
            "--rel-tol",
            "0.03",
        ],
    )

    assert result.exit_code == 0
    assert "reconcile-moneyflow summary" in result.stdout
    assert "only_tushare=1" in result.stdout


def test_cli_reconcile_moneyflow_threshold_failure(mocker) -> None:
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)

    service = mocker.Mock()
    service.run.return_value = _build_report(comparable_diff=2)
    mocker.patch("src.cli.MoneyflowReconcileService", return_value=service)

    result = CliRunner().invoke(
        app,
        [
            "reconcile-moneyflow",
            "--sample-limit",
            "0",
            "--threshold-comparable-diff",
            "1",
            "--abs-tol",
            "1",
            "--rel-tol",
            "0.03",
        ],
    )

    assert result.exit_code == 1
    assert "reconcile-moneyflow gate failed" in result.stdout
