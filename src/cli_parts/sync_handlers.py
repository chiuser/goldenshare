from __future__ import annotations

import time
from datetime import date
from typing import Callable


def run_sync_history(
    *,
    session_local,
    build_sync_service_fn,
    attach_progress_fn: Callable[..., None],
    prepare_kwargs_fn: Callable[..., dict[str, object]],
    reconciliation_service_cls,
    snapshot_service_cls,
    resources: list[str],
    ts_code: str | None,
    list_status: str | None,
    classify: str | None,
    index_code: str | None,
    con_code: str | None,
    exchange: str | None,
    exchange_id: str | None,
    ths_type: str | None,
    idx_type: str | None,
    market: str | None,
    hot_type: str | None,
    is_new: str | None,
    tag: str | None,
    limit_type: str | None,
    start_date: str | None,
    end_date: str | None,
    echo_fn: Callable[[str], None],
) -> None:
    with session_local() as session:
        reconciliation_service = reconciliation_service_cls()
        snapshot_service = snapshot_service_cls()
        for resource in resources:
            service = build_sync_service_fn(resource, session)
            attach_progress_fn(service, resource=resource)
            kwargs = {
                "ts_code": ts_code,
                "list_status": list_status,
                "classify": classify,
                "index_code": index_code,
                "con_code": con_code,
                "exchange": exchange,
                "exchange_id": exchange_id,
                "type": ths_type,
                "idx_type": idx_type,
                "market": market,
                "hot_type": hot_type,
                "is_new": is_new,
                "tag": tag,
                "limit_type": limit_type,
                "start_date": start_date,
                "end_date": end_date,
            }
            echo_fn(f"[{resource}] sync-history start")
            started_at = time.perf_counter()
            result = service.run_full(**prepare_kwargs_fn(service, kwargs))
            if result.trade_date is None:
                reconciliation_service.refresh_resource_state_from_observed(session, resource)
            snapshot_service.refresh_resources(session, [resource])
            elapsed_seconds = max(time.perf_counter() - started_at, 0.0)
            echo_fn(
                f"[{resource}] sync-history done "
                f"fetched={result.rows_fetched} written={result.rows_written} "
                f"elapsed={elapsed_seconds:.1f}s"
            )


def run_sync_daily(
    *,
    session_local,
    resolve_default_sync_date_fn: Callable[..., date],
    build_sync_service_fn,
    attach_progress_fn: Callable[..., None],
    prepare_kwargs_fn: Callable[..., dict[str, object]],
    snapshot_service_cls,
    resources: list[str],
    trade_date_text: str | None,
    ts_code: str | None,
    exchange: str | None,
    exchange_id: str | None,
    limit_type: str | None,
    con_code: str | None,
    idx_type: str | None,
    market: str | None,
    hot_type: str | None,
    is_new: str | None,
    tag: str | None,
    echo_fn: Callable[[str], None],
) -> None:
    target_date = date.fromisoformat(trade_date_text) if trade_date_text else None
    with session_local() as session:
        snapshot_service = snapshot_service_cls()
        if target_date is None:
            target_date = resolve_default_sync_date_fn(session)
        for resource in resources:
            service = build_sync_service_fn(resource, session)
            attach_progress_fn(service, resource=resource)
            kwargs = prepare_kwargs_fn(
                service,
                {
                    "ts_code": ts_code,
                    "exchange": exchange,
                    "exchange_id": exchange_id,
                    "limit_type": limit_type,
                    "con_code": con_code,
                    "idx_type": idx_type,
                    "market": market,
                    "hot_type": hot_type,
                    "is_new": is_new,
                    "tag": tag,
                },
            )
            assert target_date is not None
            echo_fn(f"[{resource}] sync-daily start trade_date={target_date.isoformat()}")
            started_at = time.perf_counter()
            result = service.run_incremental(trade_date=target_date, **kwargs)
            snapshot_service.refresh_resources(session, [resource])
            elapsed_seconds = max(time.perf_counter() - started_at, 0.0)
            echo_fn(
                f"[{resource}] sync-daily done "
                f"fetched={result.rows_fetched} written={result.rows_written} "
                f"elapsed={elapsed_seconds:.1f}s"
            )


def run_sync_snapshot(
    *,
    session_local,
    build_sync_service_fn,
    attach_progress_fn: Callable[..., None],
    prepare_kwargs_fn: Callable[..., dict[str, object]],
    reconciliation_service_cls,
    snapshot_service_cls,
    resources: list[str],
    source_key: str | None,
    ts_code: str | None,
    list_status: str | None,
    classify: str | None,
    index_code: str | None,
    con_code: str | None,
    exchange: str | None,
    exchange_id: str | None,
    ths_type: str | None,
    idx_type: str | None,
    market: str | None,
    hot_type: str | None,
    is_new: str | None,
    tag: str | None,
    limit_type: str | None,
    echo_fn: Callable[[str], None],
) -> None:
    with session_local() as session:
        reconciliation_service = reconciliation_service_cls()
        snapshot_service = snapshot_service_cls()
        for resource in resources:
            service = build_sync_service_fn(resource, session)
            attach_progress_fn(service, resource=resource)
            kwargs = {
                "source_key": source_key,
                "ts_code": ts_code,
                "list_status": list_status,
                "classify": classify,
                "index_code": index_code,
                "con_code": con_code,
                "exchange": exchange,
                "exchange_id": exchange_id,
                "type": ths_type,
                "idx_type": idx_type,
                "market": market,
                "hot_type": hot_type,
                "is_new": is_new,
                "tag": tag,
                "limit_type": limit_type,
            }
            echo_fn(f"[{resource}] sync-snapshot start")
            started_at = time.perf_counter()
            result = service.run_full(**prepare_kwargs_fn(service, kwargs))
            if result.trade_date is None:
                reconciliation_service.refresh_resource_state_from_observed(session, resource)
            snapshot_service.refresh_resources(session, [resource])
            elapsed_seconds = max(time.perf_counter() - started_at, 0.0)
            echo_fn(
                f"[{resource}] sync-snapshot done "
                f"fetched={result.rows_fetched} written={result.rows_written} "
                f"elapsed={elapsed_seconds:.1f}s"
            )
