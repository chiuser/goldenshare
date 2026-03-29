from __future__ import annotations

from typer.testing import CliRunner

from src.cli import app


def test_backfill_fund_series_invokes_history_backfill_service(mocker) -> None:
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)

    history_backfill_service = mocker.Mock()
    history_backfill_service.backfill_fund_series.return_value = mocker.Mock(
        resource="fund_daily",
        units_processed=1,
        rows_fetched=5,
        rows_written=5,
    )
    history_backfill_cls = mocker.patch("src.cli.HistoryBackfillService", return_value=history_backfill_service)

    result = CliRunner().invoke(
        app,
        [
            "backfill-fund-series",
            "--resource",
            "fund_daily",
            "--start-date",
            "2010-01-01",
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
    history_backfill_service.backfill_fund_series.assert_called_once()
    kwargs = history_backfill_service.backfill_fund_series.call_args.kwargs
    assert kwargs["resource"] == "fund_daily"
    assert kwargs["start_date"].isoformat() == "2010-01-01"
    assert kwargs["end_date"].isoformat() == "2026-03-29"
    assert kwargs["offset"] == 0
    assert kwargs["limit"] == 10
    assert callable(kwargs["progress"])
    assert "fund_daily: units=1 fetched=5 written=5" in result.stdout
