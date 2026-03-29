from __future__ import annotations

from typer.testing import CliRunner

from src.cli import app


def test_backfill_index_series_invokes_history_backfill_service(mocker) -> None:
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)

    history_backfill_service = mocker.Mock()
    history_backfill_service.backfill_index_series.return_value = mocker.Mock(
        resource="index_weekly",
        units_processed=1,
        rows_fetched=5,
        rows_written=5,
    )
    history_backfill_cls = mocker.patch("src.cli.HistoryBackfillService", return_value=history_backfill_service)

    result = CliRunner().invoke(
        app,
        [
            "backfill-index-series",
            "--resource",
            "index_weekly",
            "--start-date",
            "2020-01-01",
            "--end-date",
            "2026-03-29",
            "--offset",
            "0",
            "--limit",
            "10",
        ],
    )

    assert result.exit_code == 0
    history_backfill_cls.assert_called_once_with(session)
    history_backfill_service.backfill_index_series.assert_called_once()
    kwargs = history_backfill_service.backfill_index_series.call_args.kwargs
    assert kwargs["resource"] == "index_weekly"
    assert kwargs["start_date"].isoformat() == "2020-01-01"
    assert kwargs["end_date"].isoformat() == "2026-03-29"
    assert kwargs["offset"] == 0
    assert kwargs["limit"] == 10
    assert callable(kwargs["progress"])
    assert "index_weekly: units=1 fetched=5 written=5" in result.stdout
