from __future__ import annotations

from typer.testing import CliRunner

from src.cli import app
from src.operations.services.indicator_state_reconcile_service import (
    IndicatorStateIssueSample,
    IndicatorStateReconcileReport,
)


def _build_report(*, missing: int, stale: int, mismatch: int, factor_mismatch: int) -> IndicatorStateReconcileReport:
    return IndicatorStateReconcileReport(
        total_codes=2,
        expected_states=12,
        existing_states=10,
        missing_state=missing,
        stale_state=stale,
        bar_count_mismatch=mismatch,
        adj_factor_mismatch=factor_mismatch,
        samples={
            "missing_state": [
                IndicatorStateIssueSample(
                    ts_code="000001.SZ",
                    adjustment="forward",
                    indicator_name="rsi",
                    issue_type="missing_state",
                    detail="状态缺失",
                )
            ],
            "stale_state": [],
            "bar_count_mismatch": [],
            "adj_factor_mismatch": [],
        },
    )


def test_cli_reconcile_indicator_state_success(mocker) -> None:
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)

    service = mocker.Mock()
    service.run.return_value = _build_report(missing=0, stale=0, mismatch=0, factor_mismatch=0)
    mocker.patch("src.cli.IndicatorStateReconcileService", return_value=service)

    result = CliRunner().invoke(app, ["reconcile-indicator-state", "--sample-limit", "0"])

    assert result.exit_code == 0
    assert "reconcile-indicator-state summary" in result.stdout
    assert "missing_state=0" in result.stdout


def test_cli_reconcile_indicator_state_threshold_failure(mocker) -> None:
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)

    service = mocker.Mock()
    service.run.return_value = _build_report(missing=2, stale=0, mismatch=0, factor_mismatch=0)
    mocker.patch("src.cli.IndicatorStateReconcileService", return_value=service)

    result = CliRunner().invoke(
        app,
        [
            "reconcile-indicator-state",
            "--sample-limit",
            "0",
            "--threshold-missing-state",
            "1",
        ],
    )

    assert result.exit_code == 1
    assert "reconcile-indicator-state gate failed" in result.stdout
