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


def run_backfill_trade_cal(
    *,
    session_local,
    history_backfill_service_cls,
    snapshot_service_cls,
    start_date: str,
    end_date: str,
    exchange: str | None,
    echo_fn: Callable[[str], None],
) -> None:
    with session_local() as session:
        service = history_backfill_service_cls(session)
        summary = service.backfill_trade_calendar(date.fromisoformat(start_date), date.fromisoformat(end_date), exchange=exchange)
        snapshot_service_cls().refresh_resources(session, ["trade_cal"])
        echo_fn(f"{summary.resource}: units={summary.units_processed} fetched={summary.rows_fetched} written={summary.rows_written}")


def run_backfill_equity_series(
    *,
    session_local,
    history_backfill_service_cls,
    snapshot_service_cls,
    resource: str,
    start_date: str,
    end_date: str,
    offset: int,
    limit: int | None,
    echo_fn: Callable[[str], None],
) -> None:
    with session_local() as session:
        service = history_backfill_service_cls(session)
        summary = service.backfill_equity_series(
            resource=resource,
            start_date=date.fromisoformat(start_date),
            end_date=date.fromisoformat(end_date),
            offset=offset,
            limit=limit,
            progress=echo_fn,
        )
        snapshot_service_cls().refresh_resources(session, [resource])
        echo_fn(f"{summary.resource}: units={summary.units_processed} fetched={summary.rows_fetched} written={summary.rows_written}")


def run_backfill_by_trade_date(
    *,
    session_local,
    history_backfill_service_cls,
    snapshot_service_cls,
    resource: str,
    start_date: str,
    end_date: str,
    exchange: str | None,
    exchange_id: str | None,
    limit_type: str | None,
    ts_code: str | None,
    con_code: str | None,
    idx_type: str | None,
    market: str | None,
    hot_type: str | None,
    is_new: str | None,
    offset: int,
    limit: int | None,
    echo_fn: Callable[[str], None],
) -> None:
    with session_local() as session:
        service = history_backfill_service_cls(session)
        summary = service.backfill_by_trade_dates(
            resource=resource,
            start_date=date.fromisoformat(start_date),
            end_date=date.fromisoformat(end_date),
            exchange=exchange,
            exchange_id=exchange_id,
            limit_type=limit_type,
            ts_code=ts_code,
            con_code=con_code,
            idx_type=idx_type,
            market=market,
            hot_type=hot_type,
            is_new=is_new,
            offset=offset,
            limit=limit,
            progress=echo_fn,
        )
        snapshot_service_cls().refresh_resources(session, [resource])
        echo_fn(f"{summary.resource}: units={summary.units_processed} fetched={summary.rows_fetched} written={summary.rows_written}")


def run_backfill_by_date_range(
    *,
    session_local,
    build_sync_service_fn,
    reconciliation_service_cls,
    snapshot_service_cls,
    resource: str,
    start_date: str,
    end_date: str,
    ts_code: str | None,
    idx_type: str | None,
    tag: str | None,
    echo_fn: Callable[[str], None],
) -> None:
    if resource not in {"ths_daily", "dc_index", "dc_daily", "kpl_list"}:
        raise typer.BadParameter("resource must be one of: ths_daily, dc_index, dc_daily, kpl_list")
    with session_local() as session:
        reconciliation_service = reconciliation_service_cls()
        snapshot_service = snapshot_service_cls()
        service = build_sync_service_fn(resource, session)
        run_kwargs = {
            "ts_code": ts_code,
            "idx_type": idx_type,
            "start_date": start_date,
            "end_date": end_date,
        }
        if resource == "kpl_list":
            run_kwargs["tag"] = tag
        result = service.run_full(**run_kwargs)
        reconciliation_service.refresh_resource_state_from_observed(session, resource)
        snapshot_service.refresh_resources(session, [resource])
        echo_fn(f"{resource}: units=1 fetched={result.rows_fetched} written={result.rows_written}")


def run_backfill_low_frequency(
    *,
    session_local,
    history_backfill_service_cls,
    snapshot_service_cls,
    resource: str,
    offset: int,
    limit: int | None,
    echo_fn: Callable[[str], None],
) -> None:
    with session_local() as session:
        service = history_backfill_service_cls(session)
        summary = service.backfill_low_frequency_by_security(
            resource=resource,
            offset=offset,
            limit=limit,
            progress=echo_fn,
        )
        snapshot_service_cls().refresh_resources(session, [resource])
        echo_fn(f"{summary.resource}: units={summary.units_processed} fetched={summary.rows_fetched} written={summary.rows_written}")


def run_backfill_fund_series(
    *,
    session_local,
    history_backfill_service_cls,
    resource: str,
    start_date: str,
    end_date: str,
    offset: int,
    limit: int | None,
    echo_fn: Callable[[str], None],
) -> None:
    with session_local() as session:
        service = history_backfill_service_cls(session)
        summary = service.backfill_fund_series(
            resource=resource,
            start_date=date.fromisoformat(start_date),
            end_date=date.fromisoformat(end_date),
            offset=offset,
            limit=limit,
            progress=echo_fn,
        )
        echo_fn(f"{summary.resource}: units={summary.units_processed} fetched={summary.rows_fetched} written={summary.rows_written}")


def run_backfill_index_series(
    *,
    session_local,
    history_backfill_service_cls,
    resource: str,
    start_date: str,
    end_date: str,
    offset: int,
    limit: int | None,
    echo_fn: Callable[[str], None],
) -> None:
    with session_local() as session:
        service = history_backfill_service_cls(session)
        summary = service.backfill_index_series(
            resource=resource,
            start_date=date.fromisoformat(start_date),
            end_date=date.fromisoformat(end_date),
            offset=offset,
            limit=limit,
            progress=echo_fn,
        )
        echo_fn(f"{summary.resource}: units={summary.units_processed} fetched={summary.rows_fetched} written={summary.rows_written}")
