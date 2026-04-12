from __future__ import annotations

from typer.testing import CliRunner

from src.cli import app
from src.operations.services.stock_basic_reconcile_service import StockBasicDiffSample, StockBasicReconcileReport


def _build_report(comparable_diff: int) -> StockBasicReconcileReport:
    return StockBasicReconcileReport(
        total_union=4,
        comparable=2,
        only_tushare=1,
        only_biying=1,
        comparable_diff=comparable_diff,
        samples={
            "only_tushare": [
                StockBasicDiffSample(
                    ts_code="000003.SZ",
                    diff_type="only_tushare",
                    tushare_name="只在左侧",
                    biying_name=None,
                    tushare_exchange="SZSE",
                    biying_exchange=None,
                    tushare_name_norm="只在左侧",
                    biying_name_norm="",
                    tushare_exchange_norm="SZ",
                    biying_exchange_norm="",
                )
            ],
            "only_biying": [],
            "comparable_diff": [],
        },
    )


def test_cli_reconcile_stock_basic_success(mocker) -> None:
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)

    service = mocker.Mock()
    service.run.return_value = _build_report(comparable_diff=0)
    mocker.patch("src.cli.StockBasicReconcileService", return_value=service)

    result = CliRunner().invoke(app, ["reconcile-stock-basic", "--sample-limit", "0"])

    assert result.exit_code == 0
    assert "reconcile-stock-basic summary" in result.stdout
    assert "only_tushare=1" in result.stdout


def test_cli_reconcile_stock_basic_threshold_failure(mocker) -> None:
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)

    service = mocker.Mock()
    service.run.return_value = _build_report(comparable_diff=2)
    mocker.patch("src.cli.StockBasicReconcileService", return_value=service)

    result = CliRunner().invoke(
        app,
        [
            "reconcile-stock-basic",
            "--sample-limit",
            "0",
            "--threshold-comparable-diff",
            "1",
        ],
    )

    assert result.exit_code == 1
    assert "reconcile-stock-basic gate failed" in result.stdout
