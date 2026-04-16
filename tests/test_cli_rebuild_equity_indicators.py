from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from typer.testing import CliRunner

from src.cli import app


def _mock_session_context(mocker):
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)
    return session


def test_cli_rebuild_equity_indicators_runs_purge_and_sync(mocker) -> None:
    session = _mock_session_context(mocker)
    session.execute.side_effect = [SimpleNamespace(rowcount=1) for _ in range(7)]

    sync_service = mocker.Mock()
    sync_service.run_full.return_value = SimpleNamespace(
        rows_fetched=12,
        rows_written=36,
        trade_date=date(2026, 4, 16),
        message="stocks=2 bars=12",
    )
    mocker.patch("src.cli.build_sync_service", return_value=sync_service)

    reconcile_service = mocker.Mock()
    snapshot_service = mocker.Mock()
    mocker.patch("src.cli.SyncJobStateReconciliationService", return_value=reconcile_service)
    mocker.patch("src.cli.DatasetStatusSnapshotService", return_value=snapshot_service)

    result = CliRunner().invoke(app, ["rebuild-equity-indicators"])

    assert result.exit_code == 0
    assert "rebuild-equity-indicators purge summary" in result.stdout
    assert "rebuild-equity-indicators done" in result.stdout
    assert session.execute.call_count == 7
    sync_service.run_full.assert_called_once_with(source_key="tushare")
    reconcile_service.refresh_resource_state_from_observed.assert_called_once_with(session, "equity_indicators")
    snapshot_service.refresh_resources.assert_called_once_with(session, ["equity_indicators"])
    assert session.commit.called


def test_cli_rebuild_equity_indicators_skip_sync_with_ts_code(mocker) -> None:
    session = _mock_session_context(mocker)
    session.execute.side_effect = [SimpleNamespace(rowcount=0) for _ in range(7)]
    build_sync_service = mocker.patch("src.cli.build_sync_service")

    result = CliRunner().invoke(
        app,
        ["rebuild-equity-indicators", "--ts-code", "000001.sz", "--skip-sync"],
    )

    assert result.exit_code == 0
    assert "skip_sync=true: 仅清理，不执行重算。" in result.stdout
    assert session.execute.call_count == 7
    build_sync_service.assert_not_called()
