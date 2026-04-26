from __future__ import annotations

import time
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Callable

import typer


def run_ops_rebuild_dataset_status(*, session_local, dataset_status_snapshot_service_cls, echo_fn: Callable[[str], None]) -> None:
    with session_local() as session:
        count = dataset_status_snapshot_service_cls().rebuild_all(session, strict=True)
        echo_fn(f"ops-rebuild-dataset-status: rebuilt={count}")


def run_ops_daily_health_report(
    *,
    session_local,
    daily_health_report_service_cls,
    report_date_text: str | None,
    output_format: str,
    output: Path | None,
    echo_fn: Callable[[str], None],
) -> None:
    target_date = date.fromisoformat(report_date_text) if report_date_text else date.today()
    format_key = output_format.strip().lower()
    if format_key not in {"md", "json"}:
        raise typer.BadParameter("--format 仅支持 md 或 json")

    with session_local() as session:
        service = daily_health_report_service_cls()
        report = service.build_report(session, report_date=target_date)
        rendered = service.render_markdown(report) if format_key == "md" else report.to_json()

    if output is None:
        echo_fn(rendered)
        return

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    echo_fn(f"ops-daily-health-report: written={output}")


def run_ops_validate_market_mood(
    *,
    session_local,
    validation_service_cls,
    start_date_text: str | None,
    end_date_text: str | None,
    exchange: str,
    train_days: int,
    valid_days: int,
    test_days: int,
    roll_days: int,
    min_state_samples: int,
    max_signal_days: int | None,
    delta_temp: float,
    delta_emotion: float,
    include_points: bool,
    output: Path | None,
    echo_fn: Callable[[str], None],
) -> None:
    parsed_start = date.fromisoformat(start_date_text) if start_date_text else None
    parsed_end = date.fromisoformat(end_date_text) if end_date_text else None
    if parsed_start is not None and parsed_end is not None and parsed_start > parsed_end:
        raise typer.BadParameter("start_date 不能晚于 end_date")

    with session_local() as session:
        report = validation_service_cls().run(
            session,
            start_date=parsed_start,
            end_date=parsed_end,
            exchange=exchange,
            train_days=train_days,
            valid_days=valid_days,
            test_days=test_days,
            roll_days=roll_days,
            min_state_samples=min_state_samples,
            max_signal_days=max_signal_days,
            delta_temp=delta_temp,
            delta_emotion=delta_emotion,
            progress_callback=echo_fn,
        )
        rendered = report.to_json(include_points=include_points)

    if output is None:
        echo_fn(rendered)
        return

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    echo_fn(f"ops-validate-market-mood: written={output}")


def run_reconcile_stock_basic(
    *,
    session_local,
    reconcile_service_cls,
    sample_limit: int,
    threshold_only_tushare: int,
    threshold_only_biying: int,
    threshold_comparable_diff: int,
    echo_fn: Callable[[str], None],
) -> None:
    with session_local() as session:
        report = reconcile_service_cls().run(session, sample_limit=sample_limit)

    echo_fn("reconcile-stock-basic summary")
    echo_fn(f"total_union={report.total_union}")
    echo_fn(f"comparable={report.comparable}")
    echo_fn(f"only_tushare={report.only_tushare}")
    echo_fn(f"only_biying={report.only_biying}")
    echo_fn(f"comparable_diff={report.comparable_diff}")

    if sample_limit > 0:
        for diff_type in ("only_tushare", "only_biying", "comparable_diff"):
            items = report.samples[diff_type]
            if not items:
                continue
            echo_fn(f"\n[{diff_type}] samples={len(items)}")
            for item in items:
                echo_fn(
                    " - "
                    f"{item.ts_code} "
                    f"t_name={item.tushare_name!r} b_name={item.biying_name!r} "
                    f"t_exchange={item.tushare_exchange!r} b_exchange={item.biying_exchange!r} "
                    f"t_name_norm={item.tushare_name_norm!r} b_name_norm={item.biying_name_norm!r} "
                    f"t_exchange_norm={item.tushare_exchange_norm!r} b_exchange_norm={item.biying_exchange_norm!r}"
                )

    failed_checks: list[str] = []
    if threshold_only_tushare >= 0 and report.only_tushare > threshold_only_tushare:
        failed_checks.append(f"only_tushare={report.only_tushare} > threshold={threshold_only_tushare}")
    if threshold_only_biying >= 0 and report.only_biying > threshold_only_biying:
        failed_checks.append(f"only_biying={report.only_biying} > threshold={threshold_only_biying}")
    if threshold_comparable_diff >= 0 and report.comparable_diff > threshold_comparable_diff:
        failed_checks.append(f"comparable_diff={report.comparable_diff} > threshold={threshold_comparable_diff}")

    if failed_checks:
        echo_fn("\nreconcile-stock-basic gate failed:")
        for check in failed_checks:
            echo_fn(f" - {check}")
        raise typer.Exit(code=1)


def run_reconcile_moneyflow(
    *,
    session_local,
    reconcile_service_cls,
    start_date_text: str | None,
    end_date_text: str | None,
    range_days: int,
    sample_limit: int,
    abs_tol: float,
    rel_tol: float,
    threshold_only_tushare: int,
    threshold_only_biying: int,
    threshold_comparable_diff: int,
    echo_fn: Callable[[str], None],
) -> None:
    parsed_start = date.fromisoformat(start_date_text) if start_date_text else None
    parsed_end = date.fromisoformat(end_date_text) if end_date_text else None
    with session_local() as session:
        report = reconcile_service_cls().run(
            session,
            start_date=parsed_start,
            end_date=parsed_end,
            range_days=range_days,
            sample_limit=sample_limit,
            abs_tol=Decimal(str(abs_tol)),
            rel_tol=Decimal(str(rel_tol)),
        )

    echo_fn("reconcile-moneyflow summary")
    echo_fn(f"date_range={report.start_date.isoformat()}~{report.end_date.isoformat()}")
    echo_fn(f"total_union={report.total_union}")
    echo_fn(f"comparable={report.comparable}")
    echo_fn(f"only_tushare={report.only_tushare}")
    echo_fn(f"only_biying={report.only_biying}")
    echo_fn(f"comparable_diff={report.comparable_diff}")
    echo_fn(f"direction_mismatch={report.direction_mismatch}")

    if sample_limit > 0:
        for diff_type in ("only_tushare", "only_biying", "comparable_diff"):
            items = report.samples[diff_type]
            if not items:
                continue
            echo_fn(f"\n[{diff_type}] samples={len(items)}")
            for item in items:
                echo_fn(
                    " - "
                    f"{item.ts_code} {item.trade_date.isoformat()} "
                    f"field={item.field or '-'} "
                    f"t={item.tushare_value} b={item.biying_value} "
                    f"abs_diff={item.abs_diff} rel_diff={item.rel_diff} "
                    f"note={item.note or '-'}"
                )

    failed_checks: list[str] = []
    if threshold_only_tushare >= 0 and report.only_tushare > threshold_only_tushare:
        failed_checks.append(f"only_tushare={report.only_tushare} > threshold={threshold_only_tushare}")
    if threshold_only_biying >= 0 and report.only_biying > threshold_only_biying:
        failed_checks.append(f"only_biying={report.only_biying} > threshold={threshold_only_biying}")
    if threshold_comparable_diff >= 0 and report.comparable_diff > threshold_comparable_diff:
        failed_checks.append(f"comparable_diff={report.comparable_diff} > threshold={threshold_comparable_diff}")

    if failed_checks:
        echo_fn("\nreconcile-moneyflow gate failed:")
        for check in failed_checks:
            echo_fn(f" - {check}")
        raise typer.Exit(code=1)


def run_ops_seed_default_single_source(
    *,
    session_local,
    service_cls,
    source_key: str,
    apply: bool,
    echo_fn: Callable[[str], None],
) -> None:
    with session_local() as session:
        report = service_cls().run(
            session,
            source_key=source_key,
            dry_run=not apply,
        )

    mode = "apply" if apply else "dry-run"
    echo_fn(f"ops-seed-default-single-source [{mode}] source={report.source_key}")
    echo_fn(f"dataset_total={report.dataset_total}")
    echo_fn(f"created_mapping_rules={report.created_mapping_rules}")
    echo_fn(f"created_cleansing_rules={report.created_cleansing_rules}")
    echo_fn(f"created_resolution_policies={report.created_resolution_policies}")
    echo_fn(f"created_source_statuses={report.created_source_statuses}")


def run_ops_seed_moneyflow_multi_source(
    *,
    session_local,
    service_cls,
    apply: bool,
    echo_fn: Callable[[str], None],
) -> None:
    with session_local() as session:
        report = service_cls().run(session, dry_run=not apply)

    mode = "apply" if apply else "dry-run"
    echo_fn(f"ops-seed-moneyflow-multi-source [{mode}] dataset={report.dataset_key}")
    echo_fn(f"created_mapping_rules={report.created_mapping_rules}")
    echo_fn(f"created_cleansing_rules={report.created_cleansing_rules}")
    echo_fn(f"created_source_statuses={report.created_source_statuses}")
    echo_fn(f"created_resolution_policy={report.created_resolution_policy}")
    echo_fn(f"updated_resolution_policy={report.updated_resolution_policy}")


def run_ops_scheduler_tick(
    *,
    session_local,
    scheduler_cls,
    limit: int,
    echo_fn: Callable[[str], None],
) -> None:
    with session_local() as session:
        task_runs = scheduler_cls().run_once(session, limit=limit)
        for task_run in task_runs:
            echo_fn(
                "scheduled "
                f"task_run#{task_run.id} "
                f"schedule_id={task_run.schedule_id} "
                f"resource={task_run.resource_key or '-'} "
                f"status={task_run.status}"
            )
        echo_fn(f"ops-scheduler-tick: scheduled={len(task_runs)}")


def run_ops_worker_run(
    *,
    session_local,
    worker_cls,
    auto_reconcile_fn: Callable[..., int],
    open_task_run_counts_fn: Callable[..., tuple[int, int]],
    limit: int,
    auto_reconcile_stale_for_minutes: int,
    auto_reconcile_limit: int,
    echo_fn: Callable[[str], None],
) -> None:
    with session_local() as session:
        reconciled = auto_reconcile_fn(
            session,
            stale_for_minutes=auto_reconcile_stale_for_minutes,
            limit=auto_reconcile_limit,
        )
        worker = worker_cls()
        processed = 0
        for _ in range(limit):
            task_run = worker.run_next(session)
            if task_run is None:
                break
            processed += 1
            echo_fn(
                "processed "
                f"task_run#{task_run.id} "
                f"status={task_run.status} "
                f"rows_fetched={task_run.rows_fetched} "
                f"rows_saved={task_run.rows_saved}"
            )
        queued, running = open_task_run_counts_fn(session)
        echo_fn(
            "ops-worker-run: "
            f"本轮新接任务={processed} "
            f"等待中={queued} "
            f"执行中={running} "
            f"自动收敛={reconciled}"
        )


def run_ops_scheduler_serve(
    *,
    session_local,
    scheduler_cls,
    limit: int,
    sleep_seconds: float,
    max_cycles: int | None,
    echo_fn: Callable[[str], None],
) -> None:
    cycles = 0
    while True:
        with session_local() as session:
            task_runs = scheduler_cls().run_once(session, limit=limit)
            echo_fn(f"ops-scheduler-serve: scheduled={len(task_runs)}")
        cycles += 1
        if max_cycles is not None and cycles >= max_cycles:
            break
        time.sleep(sleep_seconds)


def run_ops_worker_serve(
    *,
    session_local,
    worker_cls,
    auto_reconcile_fn: Callable[..., int],
    open_task_run_counts_fn: Callable[..., tuple[int, int]],
    limit: int,
    sleep_seconds: float,
    max_cycles: int | None,
    auto_reconcile_stale_for_minutes: int,
    auto_reconcile_limit: int,
    echo_fn: Callable[[str], None],
) -> None:
    cycles = 0
    while True:
        with session_local() as session:
            reconciled = auto_reconcile_fn(
                session,
                stale_for_minutes=auto_reconcile_stale_for_minutes,
                limit=auto_reconcile_limit,
            )
            worker = worker_cls()
            processed = 0
            for _ in range(limit):
                task_run = worker.run_next(session)
                if task_run is None:
                    break
                processed += 1
            queued, running = open_task_run_counts_fn(session)
            echo_fn(
                "ops-worker-serve: "
                f"本轮新接任务={processed} "
                f"等待中={queued} "
                f"执行中={running} "
                f"自动收敛={reconciled}"
            )
        cycles += 1
        if max_cycles is not None and cycles >= max_cycles:
            break
        time.sleep(sleep_seconds)


def run_ops_reconcile_task_runs(
    *,
    session_local,
    service_cls,
    stale_for_minutes: int,
    limit: int,
    apply: bool,
    echo_fn: Callable[[str], None],
) -> None:
    with session_local() as session:
        service = service_cls()
        if apply:
            reconciled = service.reconcile_stale_task_runs(session, stale_for_minutes=stale_for_minutes, limit=limit)
            for item in reconciled:
                echo_fn(
                    f"reconciled task_run#{item.id} {item.previous_status}->{item.new_status} reason={item.reason}"
                )
            echo_fn(f"ops-reconcile-task-runs: reconciled={len(reconciled)}")
            return

        previews = service.preview_stale_task_runs(session, stale_for_minutes=stale_for_minutes, limit=limit)
        for item in previews:
            echo_fn(
                f"stale task_run#{item.id} {item.previous_status}->{item.new_status} reason={item.reason}"
            )
        echo_fn(f"ops-reconcile-task-runs: stale={len(previews)}")
