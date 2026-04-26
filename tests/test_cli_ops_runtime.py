from __future__ import annotations

from datetime import date
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
        SimpleNamespace(id=101, schedule_id=11, resource_key=None, status="queued"),
        SimpleNamespace(id=102, schedule_id=12, resource_key="stock_basic", status="queued"),
    ]
    scheduler_cls = mocker.patch("src.cli.OperationsScheduler", return_value=scheduler)

    result = CliRunner().invoke(app, ["ops-scheduler-tick", "--limit", "10"])

    assert result.exit_code == 0
    scheduler_cls.assert_called_once_with()
    scheduler.run_once.assert_called_once_with(session, limit=10)
    assert "scheduled task_run#101 schedule_id=11 resource=- status=queued" in result.stdout
    assert "scheduled task_run#102 schedule_id=12 resource=stock_basic status=queued" in result.stdout
    assert "ops-scheduler-tick: scheduled=2" in result.stdout


def test_ops_worker_run_consumes_until_limit_or_queue_is_empty(mocker) -> None:
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)

    worker = mocker.Mock()
    worker.run_next.side_effect = [
        SimpleNamespace(id=201, status="success", rows_fetched=8, rows_saved=6),
        SimpleNamespace(id=202, status="failed", rows_fetched=3, rows_saved=0),
        None,
    ]
    worker_cls = mocker.patch("src.cli.OperationsWorker", return_value=worker)
    reconcile_service = mocker.Mock()
    reconcile_service.reconcile_stale_task_runs.return_value = []
    reconcile_cls = mocker.patch("src.cli.OperationsTaskRunReconciliationService", return_value=reconcile_service)
    mocker.patch("src.cli._open_task_run_counts", return_value=(0, 1))

    result = CliRunner().invoke(app, ["ops-worker-run", "--limit", "5"])

    assert result.exit_code == 0
    worker_cls.assert_called_once_with()
    reconcile_cls.assert_called_once_with()
    reconcile_service.reconcile_stale_task_runs.assert_called_once_with(session, stale_for_minutes=5, limit=200)
    assert worker.run_next.call_count == 3
    assert "processed task_run#201 status=success rows_fetched=8 rows_saved=6" in result.stdout
    assert "processed task_run#202 status=failed rows_fetched=3 rows_saved=0" in result.stdout
    assert "ops-worker-run: 本轮新接任务=2 等待中=0 执行中=1 自动收敛=0" in result.stdout


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
    reconcile_service = mocker.Mock()
    reconcile_service.reconcile_stale_task_runs.side_effect = [[], []]
    reconcile_cls = mocker.patch("src.cli.OperationsTaskRunReconciliationService", return_value=reconcile_service)
    open_counts = mocker.patch("src.cli._open_task_run_counts", side_effect=[(0, 1), (0, 0)])
    sleep = mocker.patch("src.cli.time.sleep")

    result = CliRunner().invoke(app, ["ops-worker-serve", "--limit", "2", "--sleep-seconds", "1", "--max-cycles", "2"])

    assert result.exit_code == 0
    worker_cls.assert_called()
    assert reconcile_cls.call_count == 2
    assert reconcile_service.reconcile_stale_task_runs.call_count == 2
    assert worker.run_next.call_count == 3
    assert open_counts.call_count == 2
    sleep.assert_called_once_with(1.0)
    assert "ops-worker-serve: 本轮新接任务=1 等待中=0 执行中=1 自动收敛=0" in result.stdout
    assert "ops-worker-serve: 本轮新接任务=0 等待中=0 执行中=0 自动收敛=0" in result.stdout


def test_ops_reconcile_task_runs_previews_by_default(mocker) -> None:
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)

    service = mocker.Mock()
    service.preview_stale_task_runs.return_value = [
        SimpleNamespace(id=8, previous_status="running", new_status="canceled", reason="任务已经收到停止请求，但长时间没有完成收尾，系统已修正为已取消。"),
    ]
    service.reconcile_stale_task_runs.return_value = []
    service_cls = mocker.patch("src.cli.OperationsTaskRunReconciliationService", return_value=service)

    result = CliRunner().invoke(app, ["ops-reconcile-task-runs", "--stale-for-minutes", "15"])

    assert result.exit_code == 0
    service_cls.assert_called_once_with()
    service.preview_stale_task_runs.assert_called_once_with(session, stale_for_minutes=15, limit=200)
    assert "stale task_run#8 running->canceled" in result.stdout
    assert "ops-reconcile-task-runs: stale=1" in result.stdout


def test_ops_reconcile_task_runs_apply_repairs_statuses(mocker) -> None:
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)

    service = mocker.Mock()
    service.preview_stale_task_runs.return_value = []
    service.reconcile_stale_task_runs.return_value = [
        SimpleNamespace(id=7, previous_status="running", new_status="failed", reason="任务长时间没有任何新进展，推定已经中断，系统已修正为执行失败。"),
    ]
    service_cls = mocker.patch("src.cli.OperationsTaskRunReconciliationService", return_value=service)

    result = CliRunner().invoke(app, ["ops-reconcile-task-runs", "--apply"])

    assert result.exit_code == 0
    service_cls.assert_called_once_with()
    service.reconcile_stale_task_runs.assert_called_once_with(session, stale_for_minutes=30, limit=200)
    assert "reconciled task_run#7 running->failed" in result.stdout
    assert "ops-reconcile-task-runs: reconciled=1" in result.stdout
def test_ops_rebuild_dataset_status_rebuilds_snapshots(mocker) -> None:
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)

    service = mocker.Mock()
    service.rebuild_all.return_value = 28
    service_cls = mocker.patch("src.cli.DatasetStatusSnapshotService", return_value=service)

    result = CliRunner().invoke(app, ["ops-rebuild-dataset-status"])

    assert result.exit_code == 0
    service_cls.assert_called_once_with()
    service.rebuild_all.assert_called_once_with(session, strict=True)
    assert "ops-rebuild-dataset-status: rebuilt=28" in result.stdout


def test_ops_validate_market_mood_runs_service_and_prints_json(mocker) -> None:
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)

    report = mocker.Mock()
    report.to_json.return_value = '{"ok": true}'
    service = mocker.Mock()
    service.run.return_value = report
    service_cls = mocker.patch("src.cli.MarketMoodWalkForwardValidationService", return_value=service)

    result = CliRunner().invoke(
        app,
        [
            "ops-validate-market-mood",
            "--start-date",
            "2026-01-01",
            "--end-date",
            "2026-04-17",
            "--train-days",
            "120",
            "--valid-days",
            "30",
            "--test-days",
            "15",
            "--roll-days",
            "10",
            "--min-state-samples",
            "15",
            "--max-signal-days",
            "240",
            "--delta-temp",
            "4.0",
            "--delta-emotion",
            "7.0",
            "--include-points",
        ],
    )

    assert result.exit_code == 0
    service_cls.assert_called_once_with()
    service.run.assert_called_once()
    run_kwargs = service.run.call_args.kwargs
    assert run_kwargs["start_date"] == date(2026, 1, 1)
    assert run_kwargs["end_date"] == date(2026, 4, 17)
    assert run_kwargs["train_days"] == 120
    assert run_kwargs["valid_days"] == 30
    assert run_kwargs["test_days"] == 15
    assert run_kwargs["roll_days"] == 10
    assert run_kwargs["min_state_samples"] == 15
    assert run_kwargs["max_signal_days"] == 240
    assert run_kwargs["delta_temp"] == 4.0
    assert run_kwargs["delta_emotion"] == 7.0
    assert callable(run_kwargs["progress_callback"])
    report.to_json.assert_called_once_with(include_points=True)
    assert '{"ok": true}' in result.stdout


def test_ops_validate_market_mood_rejects_reverse_date_range() -> None:
    result = CliRunner().invoke(
        app,
        [
            "ops-validate-market-mood",
            "--start-date",
            "2026-04-17",
            "--end-date",
            "2026-01-01",
        ],
    )

    assert result.exit_code == 2


def test_refresh_serving_light_invokes_refresh_service(mocker) -> None:
    session_context = mocker.MagicMock()
    session = mocker.Mock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    mocker.patch("src.cli.SessionLocal", return_value=session_context)

    service = mocker.Mock()
    service.refresh_equity_daily_bar.return_value = SimpleNamespace(touched_rows=1234)
    service_cls = mocker.patch("src.cli.ServingLightRefreshService", return_value=service)

    result = CliRunner().invoke(
        app,
        [
            "refresh-serving-light",
            "--dataset",
            "equity_daily_bar",
            "--start-date",
            "2026-01-01",
            "--end-date",
            "2026-01-31",
            "--ts-code",
            "000001.SZ",
        ],
    )

    assert result.exit_code == 0
    service_cls.assert_called_once_with()
    service.refresh_equity_daily_bar.assert_called_once()
    assert "refresh-serving-light done dataset=equity_daily_bar" in result.stdout
    assert "touched_rows=1234" in result.stdout
