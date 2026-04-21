from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from typer.testing import CliRunner

from src.cli import app


def test_sync_daily_filters_generic_kwargs_for_v2_contract(mocker) -> None:
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)

    service = mocker.Mock()
    service.contract = SimpleNamespace(
        input_schema=SimpleNamespace(
            fields=(
                SimpleNamespace(name="exchange"),
                SimpleNamespace(name="trade_date"),
            )
        )
    )
    mocker.patch("src.cli.build_sync_service", return_value=service)
    snapshot_service = mocker.Mock()
    mocker.patch("src.cli.DatasetStatusSnapshotService", return_value=snapshot_service)

    result = CliRunner().invoke(
        app,
        [
            "sync-daily",
            "--resources",
            "trade_cal",
            "--trade-date",
            "2026-04-21",
            "--exchange",
            "SSE",
            "--con-code",
            "BK1234",
        ],
    )

    assert result.exit_code == 0
    service.run_incremental.assert_called_once_with(trade_date=date(2026, 4, 21), exchange="SSE")
    snapshot_service.refresh_resources.assert_called_once_with(session, ["trade_cal"])


def test_sync_history_filters_generic_kwargs_for_v2_contract(mocker) -> None:
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)

    service = mocker.Mock()
    service.contract = SimpleNamespace(
        input_schema=SimpleNamespace(
            fields=(
                SimpleNamespace(name="exchange"),
                SimpleNamespace(name="start_date"),
                SimpleNamespace(name="end_date"),
            )
        )
    )
    service.run_full.return_value = mocker.Mock(trade_date=None)
    mocker.patch("src.cli.build_sync_service", return_value=service)
    snapshot_service = mocker.Mock()
    mocker.patch("src.cli.DatasetStatusSnapshotService", return_value=snapshot_service)
    reconciliation = mocker.Mock()
    mocker.patch("src.cli.SyncJobStateReconciliationService", return_value=reconciliation)

    result = CliRunner().invoke(
        app,
        [
            "sync-history",
            "--resources",
            "trade_cal",
            "--exchange",
            "SSE",
            "--idx-type",
            "concept",
            "--start-date",
            "2026-04-01",
            "--end-date",
            "2026-04-21",
        ],
    )

    assert result.exit_code == 0
    service.run_full.assert_called_once_with(
        exchange="SSE",
        start_date="2026-04-01",
        end_date="2026-04-21",
    )
    reconciliation.refresh_resource_state_from_observed.assert_called_once_with(session, "trade_cal")
    snapshot_service.refresh_resources.assert_called_once_with(session, ["trade_cal"])
