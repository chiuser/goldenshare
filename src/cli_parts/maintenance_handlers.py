from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Callable

import typer


def run_refresh_serving_light(
    *,
    session_local,
    refresh_service_cls,
    dataset: str,
    start_date: str | None,
    end_date: str | None,
    ts_code: str | None,
    echo_fn: Callable[[str], None],
) -> None:
    dataset_key = dataset.strip().lower()
    if dataset_key != "equity_daily_bar":
        raise typer.BadParameter("当前仅支持 --dataset equity_daily_bar")

    parsed_start = date.fromisoformat(start_date) if start_date else None
    parsed_end = date.fromisoformat(end_date) if end_date else None
    if parsed_start is not None and parsed_end is not None and parsed_start > parsed_end:
        raise typer.BadParameter("start_date 不能晚于 end_date")

    normalized_ts_code = ts_code.strip().upper() if ts_code else None
    with session_local() as session:
        result = refresh_service_cls().refresh_equity_daily_bar(
            session,
            start_date=parsed_start,
            end_date=parsed_end,
            ts_code=normalized_ts_code,
        )
    echo_fn(
        "refresh-serving-light done "
        f"dataset={dataset_key} "
        f"ts_code={normalized_ts_code or '*'} "
        f"start_date={parsed_start} "
        f"end_date={parsed_end} "
        f"touched_rows={result.touched_rows}"
    )


def run_reconcile_dataset(
    *,
    session_local,
    reconcile_service_cls,
    dataset: str,
    start_date: str | None,
    end_date: str | None,
    sample_limit: int,
    abs_diff_threshold: int,
    echo_fn: Callable[[str], None],
) -> None:
    parsed_start = date.fromisoformat(start_date) if start_date else None
    parsed_end = date.fromisoformat(end_date) if end_date else None
    with session_local() as session:
        report = reconcile_service_cls().run(
            session,
            dataset_key=dataset.strip(),
            start_date=parsed_start,
            end_date=parsed_end,
            sample_limit=sample_limit,
        )

    echo_fn("reconcile-dataset summary")
    echo_fn(f"dataset={report.dataset_key}")
    echo_fn(f"date_range={report.start_date.isoformat()}~{report.end_date.isoformat()}")
    echo_fn(f"raw_rows={report.raw_rows}")
    echo_fn(f"serving_rows={report.serving_rows}")
    echo_fn(f"abs_diff={report.abs_diff}")
    echo_fn(f"reconcile_mode={report.reconcile_mode}")
    if report.raw_distinct_keys is not None and report.serving_distinct_keys is not None:
        echo_fn(f"raw_distinct_keys={report.raw_distinct_keys}")
        echo_fn(f"serving_distinct_keys={report.serving_distinct_keys}")
        echo_fn(f"distinct_abs_diff={report.distinct_abs_diff}")

    if sample_limit > 0 and report.daily_diffs:
        echo_fn(f"\n[daily_diff] samples={len(report.daily_diffs)}")
        for item in report.daily_diffs:
            echo_fn(
                f" - {item.trade_date.isoformat()} raw={item.raw_rows} "
                f"serving={item.serving_rows} diff={item.diff}"
            )
    if sample_limit > 0 and report.snapshot_key_diffs:
        echo_fn(f"\n[key_diff] samples={len(report.snapshot_key_diffs)}")
        for item in report.snapshot_key_diffs:
            echo_fn(f" - {item}")

    if abs_diff_threshold >= 0:
        gate_failures: list[str] = []
        if report.abs_diff > abs_diff_threshold:
            gate_failures.append(f"abs_diff={report.abs_diff}")
        distinct_abs_diff = report.distinct_abs_diff
        if distinct_abs_diff is not None and distinct_abs_diff > abs_diff_threshold:
            gate_failures.append(f"distinct_abs_diff={distinct_abs_diff}")
        if gate_failures:
            failure_text = ", ".join(gate_failures)
            echo_fn(f"\nreconcile-dataset gate failed: {failure_text} > threshold={abs_diff_threshold}")
            raise typer.Exit(code=1)
