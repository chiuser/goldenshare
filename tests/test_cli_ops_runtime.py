from __future__ import annotations

from types import SimpleNamespace

from typer.testing import CliRunner

from src.cli import app


def test_ops_scheduler_tick_invokes_scheduler_and_prints_summary(mocker) -> None:
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)

    scheduler = mocker.Mock()
    scheduler.run_once.return_value = [
        SimpleNamespace(id=101, schedule_id=11, spec_type="workflow", spec_key="daily_market_close_sync", status="queued"),
        SimpleNamespace(id=102, schedule_id=12, spec_type="job", spec_key="sync_history.stock_basic", status="queued"),
    ]
    scheduler_cls = mocker.patch("src.cli.OperationsScheduler", return_value=scheduler)

    result = CliRunner().invoke(app, ["ops-scheduler-tick", "--limit", "10"])

    assert result.exit_code == 0
    scheduler_cls.assert_called_once_with()
    scheduler.run_once.assert_called_once_with(session, limit=10)
    assert "scheduled execution#101 schedule_id=11 spec=workflow:daily_market_close_sync status=queued" in result.stdout
    assert "scheduled execution#102 schedule_id=12 spec=job:sync_history.stock_basic status=queued" in result.stdout
    assert "ops-scheduler-tick: scheduled=2" in result.stdout


def test_ops_worker_run_consumes_until_limit_or_queue_is_empty(mocker) -> None:
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)

    worker = mocker.Mock()
    worker.run_next.side_effect = [
        SimpleNamespace(id=201, status="success", rows_fetched=8, rows_written=6),
        SimpleNamespace(id=202, status="failed", rows_fetched=3, rows_written=0),
        None,
    ]
    worker_cls = mocker.patch("src.cli.OperationsWorker", return_value=worker)

    result = CliRunner().invoke(app, ["ops-worker-run", "--limit", "5"])

    assert result.exit_code == 0
    worker_cls.assert_called_once_with()
    assert worker.run_next.call_count == 3
    assert "processed execution#201 status=success rows_fetched=8 rows_written=6" in result.stdout
    assert "processed execution#202 status=failed rows_fetched=3 rows_written=0" in result.stdout
    assert "ops-worker-run: processed=2" in result.stdout
