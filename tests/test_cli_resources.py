from typer.testing import CliRunner

from src.cli import app


def test_list_resources_includes_extended_resources() -> None:
    result = CliRunner().invoke(app, ["list-resources"])

    assert result.exit_code == 0
    assert "etf_basic" in result.stdout
    assert "hk_basic" in result.stdout
    assert "us_basic" in result.stdout
    assert "stk_period_bar_week" in result.stdout
    assert "index_weight" in result.stdout


def test_sync_history_accepts_index_code_alias(mocker) -> None:
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)
    service = mocker.Mock()
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
            "index_weight",
            "--index-code",
            "000300.SH",
            "--start-date",
            "2020-01-01",
            "--end-date",
            "2020-01-31",
        ],
    )

    assert result.exit_code == 0
    service.run_full.assert_called_once_with(
        index_code="000300.SH",
        start_date="2020-01-01",
        end_date="2020-01-31",
    )
    snapshot_service.refresh_resources.assert_called_once_with(session, ["index_weight"])


def test_sync_history_accepts_hk_and_us_filters(mocker) -> None:
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)
    service = mocker.Mock()
    service.run_full.return_value = mocker.Mock(trade_date=None)
    mocker.patch("src.cli.build_sync_service", return_value=service)
    snapshot_service = mocker.Mock()
    mocker.patch("src.cli.DatasetStatusSnapshotService", return_value=snapshot_service)
    reconciliation = mocker.Mock()
    mocker.patch("src.cli.SyncJobStateReconciliationService", return_value=reconciliation)

    hk_result = CliRunner().invoke(app, ["sync-history", "--resources", "hk_basic", "--list-status", "L"])
    assert hk_result.exit_code == 0
    service.run_full.assert_called_once_with(list_status="L")
    snapshot_service.refresh_resources.assert_called_once_with(session, ["hk_basic"])

    service.reset_mock()
    snapshot_service.reset_mock()

    us_result = CliRunner().invoke(app, ["sync-history", "--resources", "us_basic", "--classify", "EQ"])
    assert us_result.exit_code == 0
    service.run_full.assert_called_once_with(classify="EQ")
    snapshot_service.refresh_resources.assert_called_once_with(session, ["us_basic"])
