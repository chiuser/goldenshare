from __future__ import annotations

import time
from typing import Callable


def run_ingestion_snapshot(
    *,
    session_local,
    build_maintain_service_fn,
    attach_progress_fn: Callable[..., None],
    prepare_kwargs_fn: Callable[..., dict[str, object]],
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
        snapshot_service = snapshot_service_cls()
        for resource in resources:
            service = build_maintain_service_fn(resource, session)
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
            echo_fn(f"[{resource}] snapshot start")
            started_at = time.perf_counter()
            result = service.maintain(default_time_mode="none", **prepare_kwargs_fn(service, kwargs))
            snapshot_service.refresh_resources(session, [resource])
            elapsed_seconds = max(time.perf_counter() - started_at, 0.0)
            echo_fn(
                f"[{resource}] snapshot done "
                f"fetched={result.rows_fetched} written={result.rows_written} "
                f"elapsed={elapsed_seconds:.1f}s"
            )
