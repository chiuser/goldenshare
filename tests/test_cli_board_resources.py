from typer.testing import CliRunner

from src.cli import app


def test_sync_history_accepts_board_filters(mocker) -> None:
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)
    service = mocker.Mock()
    service.run_full.return_value = mocker.Mock(trade_date=None)
    mocker.patch("src.cli.build_sync_service", return_value=service)
    reconciliation = mocker.Mock()
    mocker.patch("src.cli.SyncJobStateReconciliationService", return_value=reconciliation)
    snapshot_service = mocker.Mock()
    mocker.patch("src.cli.DatasetStatusSnapshotService", return_value=snapshot_service)

    result = CliRunner().invoke(
        app,
        [
            "sync-history",
            "--resources",
            "ths_index",
            "--exchange",
            "A",
            "--type",
            "N",
        ],
    )

    assert result.exit_code == 0
    service.run_full.assert_called_once_with(exchange="A", type="N")
    reconciliation.refresh_resource_state_from_observed.assert_called_once_with(session, "ths_index")
    snapshot_service.refresh_resources.assert_called_once_with(session, ["ths_index"])


def test_backfill_by_date_range_invokes_sync_service_and_reconciliation(mocker) -> None:
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)
    service = mocker.Mock()
    service.run_full.return_value = mocker.Mock(rows_fetched=12, rows_written=12)
    mocker.patch("src.cli.build_sync_service", return_value=service)
    reconciliation = mocker.Mock()
    mocker.patch("src.cli.SyncJobStateReconciliationService", return_value=reconciliation)
    snapshot_service = mocker.Mock()
    mocker.patch("src.cli.DatasetStatusSnapshotService", return_value=snapshot_service)

    result = CliRunner().invoke(
        app,
        [
            "backfill-by-date-range",
            "--resource",
            "dc_index",
            "--start-date",
            "2026-03-01",
            "--end-date",
            "2026-03-31",
            "--idx-type",
            "concept",
        ],
    )

    assert result.exit_code == 0
    service.run_full.assert_called_once_with(
        ts_code=None,
        idx_type="concept",
        start_date="2026-03-01",
        end_date="2026-03-31",
    )
    reconciliation.refresh_resource_state_from_observed.assert_called_once_with(session, "dc_index")
    snapshot_service.refresh_resources.assert_called_once_with(session, ["dc_index"])
