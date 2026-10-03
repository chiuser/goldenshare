"""Source capture coordinator. Never builds/promotes formal weekly partitions."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

from orchestrator.defs.bootstrap.stock_weekly_capture import (
    CancelProbe,
    WeeklyCaptureError,
    WeeklyCaptureStore,
    check_capture_path,
    check_weekly_cancel,
    verify_weekly_plan_evidence,
)
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.prod_db.stock_weekly import iter_prod_weekly_batches
from orchestrator.defs.run_contracts.stock_weekly import (
    ProdWeeklyUnit,
    WeeklyPlanManifest,
)
from orchestrator.defs.stock_weekly_source import (
    WeeklySourceWorker,
    capture_weekly_source_unit,
)
from orchestrator.utils.dg_log_helper import DgStdoutLogger


def capture_prod_weekly_unit(
    connection,
    unit: ProdWeeklyUnit,
    *,
    resource,
    store: WeeklyCaptureStore,
    cancel: CancelProbe,
    progress: Callable[[int], None],
    remaining_rows: int,
) -> dict:
    attempt = store.begin_attempt(unit)
    chunks = []
    evidence = {}
    captured_rows = 0
    try:
        for index, frame in enumerate(
            iter_prod_weekly_batches(
                resource, unit, store.manifest.budget, cancel, evidence, remaining_rows
            )
        ):
            check_weekly_cancel(cancel)
            chunks.append(store.write_chunk(connection, frame, unit, attempt, index))
            captured_rows += len(frame)
            progress(captured_rows)
            check_weekly_cancel(cancel)
        return store.seal(connection, unit, chunks, evidence["source_rows"], evidence)
    except Exception as error:  # noqa: BLE001 -- Persist failure without leaking DB credentials.
        reason = (
            str(error)
            if isinstance(error, WeeklyCaptureError)
            else "prod_source_failed"
        )
        store.mark_failed(unit, reason)
        raise WeeklyCaptureError(reason) from None


def capture_weekly_history(
    manifest: WeeklyPlanManifest,
    *,
    capture_root: Path,
    prod_resource=None,
    worker: WeeklySourceWorker | None = None,
    cancel: CancelProbe = lambda: False,
    progress: Callable[[dict], None] | None = None,
    connection_factory=connect_configured_duckdb,
) -> dict:
    """Validated receipts are the sole completion facts; partial captures remain."""
    verify_weekly_plan_evidence(manifest)
    store = WeeklyCaptureStore(capture_root, manifest)
    budget = manifest.budget
    completed = 0
    source_rows = 0
    logger = DgStdoutLogger("stock_weekly_capture")
    units_by_id = {unit.unit_id: unit for unit in manifest.units}
    last_update = 0.0

    def emit(unit_id: str, chunk_rows: int = 0, *, force: bool = False) -> None:
        nonlocal last_update
        now = monotonic()
        if force or now - last_update >= budget.progress_interval_seconds:
            unit = units_by_id[unit_id]
            payload = {
                "updated_at": datetime.now(UTC).isoformat(),
                "percent": round(100 * completed / len(manifest.units), 2),
                "current_object": unit.ts_code
                if not isinstance(unit, ProdWeeklyUnit)
                else f"{len(unit.sorted_codes)} codes",
                "current_window": f"{unit.source_date_start}/{unit.source_date_end}"
                if isinstance(unit, ProdWeeklyUnit)
                else f"{unit.anchor_start}/{unit.anchor_end}",
                "stage": "capture",
                "unit_id": unit_id,
                "completed_units": completed,
                "total_units": len(manifest.units),
                "source_rows": source_rows,
                "current_chunk_rows": chunk_rows,
                "eta": "暂无法估算",
            }
            logger.stdout("progress", **payload)
            if progress:
                progress(payload)
            last_update = now

    with store.locked():
        spill = store.root / "spill"
        check_capture_path(spill)
        spill.mkdir(exist_ok=True)
        settings = DuckDBConnectionSettings(
            temp_directory=spill,
            memory_limit=budget.duckdb_memory_limit,
            threads=budget.duckdb_threads,
            max_temp_directory_size=budget.duckdb_max_temp,
        )
        with connection_factory(settings) as connection:
            connection.execute("SET autoinstall_known_extensions=false")
            connection.execute("SET autoload_known_extensions=false")
            for unit in manifest.units:
                check_weekly_cancel(cancel)
                emit(unit.unit_id, force=True)
                receipt = store.resume(connection, unit)
                if receipt is None:
                    if isinstance(unit, ProdWeeklyUnit):
                        if prod_resource is None:
                            raise WeeklyCaptureError("prod_resource_required")
                        receipt = capture_prod_weekly_unit(
                            connection,
                            unit,
                            resource=prod_resource,
                            store=store,
                            cancel=cancel,
                            remaining_rows=budget.max_phase_rows - source_rows,
                            progress=lambda rows, unit_id=unit.unit_id: emit(
                                unit_id, rows
                            ),
                        )
                    else:
                        if worker is None:
                            raise WeeklyCaptureError("weekly_worker_required")
                        receipt = capture_weekly_source_unit(
                            connection,
                            unit,
                            worker=worker,
                            store=store,
                            cancel=cancel,
                            progress=lambda unit_id=unit.unit_id: emit(unit_id),
                        )
                completed += 1
                source_rows += receipt["source_rows"]
                if source_rows > budget.max_phase_rows:
                    raise WeeklyCaptureError("phase_row_budget_exceeded")
                emit(unit.unit_id, force=True)
                check_weekly_cancel(cancel)
    return {
        "plan_hash": manifest.plan_hash,
        "completed_units": completed,
        "source_rows": source_rows,
        "status": "captured",
        "formal_writes": 0,
    }
