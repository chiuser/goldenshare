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


def test_ops_scheduler_serve_runs_multiple_cycles(mocker) -> None:
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)

    scheduler = mocker.Mock()
    scheduler.run_once.side_effect = [[], []]
    scheduler_cls = mocker.patch("src.cli.OperationsScheduler", return_value=scheduler)
    sleep = mocker.patch("src.cli.time.sleep")

    result = CliRunner().invoke(app, ["ops-scheduler-serve", "--limit", "10", "--sleep-seconds", "1", "--max-cycles", "2"])

    assert result.exit_code == 0
    scheduler_cls.assert_called()
    assert scheduler.run_once.call_count == 2
    sleep.assert_called_once_with(1.0)
    assert result.stdout.count("ops-scheduler-serve: scheduled=0") == 2


def test_ops_worker_serve_runs_multiple_cycles(mocker) -> None:
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)

    worker = mocker.Mock()
    worker.run_next.side_effect = [SimpleNamespace(id=301), None, None]
    worker_cls = mocker.patch("src.cli.OperationsWorker", return_value=worker)
    sleep = mocker.patch("src.cli.time.sleep")

    result = CliRunner().invoke(app, ["ops-worker-serve", "--limit", "2", "--sleep-seconds", "1", "--max-cycles", "2"])

    assert result.exit_code == 0
    worker_cls.assert_called()
    assert worker.run_next.call_count == 3
    sleep.assert_called_once_with(1.0)
    assert "ops-worker-serve: processed=1" in result.stdout
    assert "ops-worker-serve: processed=0" in result.stdout


def test_ops_reconcile_executions_previews_by_default(mocker) -> None:
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)

    service = mocker.Mock()
    service.preview_stale_executions.return_value = [
        SimpleNamespace(id=8, previous_status="running", new_status="canceled", reason="任务已经收到停止请求，但长时间没有完成收尾，系统已修正为已取消。"),
    ]
    service.reconcile_stale_executions.return_value = []
    service_cls = mocker.patch("src.cli.OperationsExecutionReconciliationService", return_value=service)

    result = CliRunner().invoke(app, ["ops-reconcile-executions", "--stale-for-minutes", "15"])

    assert result.exit_code == 0
    service_cls.assert_called_once_with()
    service.preview_stale_executions.assert_called_once_with(session, stale_for_minutes=15, limit=200)
    assert "stale execution#8 running->canceled" in result.stdout
    assert "ops-reconcile-executions: stale=1" in result.stdout


def test_ops_reconcile_executions_apply_repairs_statuses(mocker) -> None:
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)

    service = mocker.Mock()
    service.preview_stale_executions.return_value = []
    service.reconcile_stale_executions.return_value = [
        SimpleNamespace(id=7, previous_status="running", new_status="failed", reason="任务长时间没有任何新进展，推定已经中断，系统已修正为执行失败。"),
    ]
    service_cls = mocker.patch("src.cli.OperationsExecutionReconciliationService", return_value=service)

    result = CliRunner().invoke(app, ["ops-reconcile-executions", "--apply"])

    assert result.exit_code == 0
    service_cls.assert_called_once_with()
    service.reconcile_stale_executions.assert_called_once_with(session, stale_for_minutes=30, limit=200)
    assert "reconciled execution#7 running->failed" in result.stdout
    assert "ops-reconcile-executions: reconciled=1" in result.stdout


def test_ops_reconcile_sync_job_state_previews_by_default(mocker) -> None:
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)

    service = mocker.Mock()
    service.preview_stale_sync_job_states.return_value = [
        SimpleNamespace(
            job_name="sync_block_trade",
            previous_last_success_date="2025-12-31",
            observed_last_success_date="2026-03-26",
            target_table="core.equity_block_trade",
        ),
    ]
    service.reconcile_stale_sync_job_states.return_value = []
    service_cls = mocker.patch("src.cli.SyncJobStateReconciliationService", return_value=service)

    result = CliRunner().invoke(app, ["ops-reconcile-sync-job-state"])

    assert result.exit_code == 0
    service_cls.assert_called_once_with()
    service.preview_stale_sync_job_states.assert_called_once_with(session)
    assert "stale sync_block_trade 2025-12-31->2026-03-26 target_table=core.equity_block_trade" in result.stdout
    assert "ops-reconcile-sync-job-state: stale=1" in result.stdout


def test_ops_reconcile_sync_job_state_apply_repairs_statuses(mocker) -> None:
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)

    service = mocker.Mock()
    service.preview_stale_sync_job_states.return_value = []
    service.reconcile_stale_sync_job_states.return_value = [
        SimpleNamespace(
            job_name="sync_block_trade",
            previous_last_success_date="2025-12-31",
            observed_last_success_date="2026-03-26",
            target_table="core.equity_block_trade",
        ),
    ]
    service_cls = mocker.patch("src.cli.SyncJobStateReconciliationService", return_value=service)

    result = CliRunner().invoke(app, ["ops-reconcile-sync-job-state", "--apply"])

    assert result.exit_code == 0
    service_cls.assert_called_once_with()
    service.reconcile_stale_sync_job_states.assert_called_once_with(session)
    assert "reconciled sync_block_trade 2025-12-31->2026-03-26 target_table=core.equity_block_trade" in result.stdout
    assert "ops-reconcile-sync-job-state: reconciled=1" in result.stdout
