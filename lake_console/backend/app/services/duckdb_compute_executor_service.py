from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from lake_console.backend.app.services.duckdb_compute_plan_service import (
    _json_text,
    _relpath,
    _utc_now_iso,
    _write_json_atomic,
    _write_parquet_manifest,
)
from lake_console.backend.app.services.lake_job_state import LakeJobLockService, LakeJobStateStore
from lake_console.backend.app.settings import LakeConsoleSettings


ProgressCallback = Callable[[dict[str, Any]], None]


class DuckDbComputeExecutorService:
    """Execute prepared DuckDB compute units into tmp candidate parts only."""

    def __init__(self, *, settings: LakeConsoleSettings) -> None:
        self.settings = settings
        self.lake_root = settings.lake_root.resolve()

    def compute_stk_mins_qfq_candidates(
        self,
        *,
        run_id: str,
        progress_callback: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        manifest_root = self._manifest_root(run_id)
        if not manifest_root.exists():
            raise FileNotFoundError(f"未找到 DuckDB compute run manifest：{_relpath(manifest_root, self.lake_root)}")

        run_payload = _read_json(manifest_root / "run.json")
        if run_payload.get("job_type") != "stk_mins_qfq_clean_next":
            raise RuntimeError(f"不支持的 job_type：{run_payload.get('job_type')}")
        if run_payload.get("status") == "compute_completed":
            return {
                "run_id": run_id,
                "status": "compute_completed",
                "message": "run 已完成 candidate compute，本次未重复执行。",
                "manifest_root": _relpath(manifest_root, self.lake_root),
            }
        if run_payload.get("status") not in {"planned", "running", "failed"}:
            raise RuntimeError(f"当前 run 状态不能进入 M2 compute：{run_payload.get('status')}")

        store = LakeJobStateStore(self.lake_root)
        lock_service = LakeJobLockService(store, stale_after_seconds=self.settings.compute_stale_heartbeat_seconds)
        started = time.perf_counter()
        lock_acquired: dict[str, Any] | None = None
        connection = None
        try:
            lock_acquired = lock_service.acquire(run_id=run_id, profile_key="duckdb_compute_stk_mins_qfq")
            units = _read_manifest_rows(manifest_root / "units.parquet")
            candidate_parts = _read_manifest_rows(manifest_root / "candidate_parts.parquet")
            latest_adj_paths = _latest_adj_factor_paths(run_payload, self.lake_root)
            temp_dir = _resolve_lake_relative_path(self.lake_root, self.settings.duckdb_temp_directory)
            temp_dir.mkdir(parents=True, exist_ok=True)
            connection = _open_duckdb_connection(settings=self.settings, temp_dir=temp_dir)
            run_payload = {
                **run_payload,
                "status": "running",
                "started_at": run_payload.get("started_at") or _utc_now_iso(),
                "finished_at": None,
                "m2_started_at": _utc_now_iso(),
            }
            _write_json_atomic(manifest_root / "run.json", run_payload)
            _append_compute_event(
                manifest_root / "events.jsonl",
                {
                    "event_type": "candidate_compute_started",
                    "level": "info",
                    "message": "M2 开始执行 DuckDB candidate compute；只写 _tmp candidate_parts，不发布正式分区。",
                    "metrics": {"unit_count": len(units)},
                },
            )

            units_by_key = {str(row["unit_key"]): dict(row) for row in units}
            candidate_by_unit = {str(row["unit_key"]): dict(row) for row in candidate_parts if row.get("unit_key")}
            executed = 0
            skipped = 0
            failed = 0
            total_rows = 0
            changed_since_checkpoint = 0
            checkpoint_interval = max(1, int(self.settings.compute_checkpoint_interval_units))
            for index, unit in enumerate(units, start=1):
                unit_key = str(unit["unit_key"])
                if _candidate_is_complete(candidate_by_unit.get(unit_key), self.lake_root):
                    if str(unit.get("status")) != "succeeded":
                        units_by_key[unit_key] = {**unit, "status": "succeeded", "error_code": None}
                        changed_since_checkpoint += 1
                    skipped += 1
                    if changed_since_checkpoint >= checkpoint_interval:
                        _flush_compute_checkpoint(
                            manifest_root=manifest_root,
                            units=list(units_by_key.values()),
                            candidate_parts=list(candidate_by_unit.values()),
                            run_payload=run_payload,
                            metrics={
                                "executed_unit_count": executed,
                                "skipped_unit_count": skipped,
                                "failed_unit_count": failed,
                                "candidate_part_count": len(candidate_by_unit),
                                "candidate_row_count": sum(int(row.get("row_count") or 0) for row in candidate_by_unit.values()),
                                "last_unit_index": index,
                                "unit_count": len(units),
                            },
                        )
                        changed_since_checkpoint = 0
                        lock_service.heartbeat(run_id=run_id)
                    continue
                _emit_progress(
                    progress_callback,
                    {
                        "event": "unit_started",
                        "run_id": run_id,
                        "unit_index": index,
                        "unit_count": len(units),
                        "unit_key": unit_key,
                    },
                )
                units_by_key[unit_key] = {**unit, "status": "running", "error_code": None}
                lock_service.heartbeat(run_id=run_id)
                try:
                    part = self._compute_unit_candidate(
                        connection=connection,
                        unit=unit,
                        latest_adj_paths=latest_adj_paths,
                    )
                except Exception as exc:
                    failed += 1
                    units_by_key[unit_key] = {**unit, "status": "failed", "error_code": "LC_COMPUTE_UNIT_FAILED"}
                    _flush_compute_checkpoint(
                        manifest_root=manifest_root,
                        units=list(units_by_key.values()),
                        candidate_parts=list(candidate_by_unit.values()),
                        run_payload=run_payload,
                        metrics={
                            "executed_unit_count": executed,
                            "skipped_unit_count": skipped,
                            "failed_unit_count": failed,
                            "candidate_part_count": len(candidate_by_unit),
                            "candidate_row_count": sum(int(row.get("row_count") or 0) for row in candidate_by_unit.values()),
                            "last_unit_index": index,
                            "unit_count": len(units),
                        },
                    )
                    run_payload = {
                        **run_payload,
                        "status": "failed",
                        "finished_at": _utc_now_iso(),
                        "error": {
                            "error_code": "LC_COMPUTE_UNIT_FAILED",
                            "stage": "duckdb_candidate_compute",
                            "unit_key": unit_key,
                            "message_for_human": "DuckDB candidate 单元计算失败，正式数据未被修改。",
                            "technical_detail": str(exc),
                        },
                    }
                    _write_json_atomic(manifest_root / "run.json", run_payload)
                    _append_compute_event(
                        manifest_root / "events.jsonl",
                        {
                            "event_type": "candidate_compute_failed",
                            "level": "error",
                            "message": "DuckDB candidate 单元计算失败，正式数据未被修改。",
                            "unit_key": unit_key,
                            "error": str(exc),
                        },
                    )
                    raise
                candidate_by_unit[unit_key] = part
                units_by_key[unit_key] = {**unit, "status": "succeeded", "error_code": None}
                executed += 1
                total_rows += int(part["row_count"])
                changed_since_checkpoint += 1
                if changed_since_checkpoint >= checkpoint_interval:
                    _flush_compute_checkpoint(
                        manifest_root=manifest_root,
                        units=list(units_by_key.values()),
                        candidate_parts=list(candidate_by_unit.values()),
                        run_payload=run_payload,
                        metrics={
                            "executed_unit_count": executed,
                            "skipped_unit_count": skipped,
                            "failed_unit_count": failed,
                            "candidate_part_count": len(candidate_by_unit),
                            "candidate_row_count": sum(int(row.get("row_count") or 0) for row in candidate_by_unit.values()),
                            "last_unit_index": index,
                            "unit_count": len(units),
                        },
                    )
                    changed_since_checkpoint = 0
                lock_service.heartbeat(run_id=run_id)
                _emit_progress(
                    progress_callback,
                    {
                        "event": "unit_succeeded",
                        "run_id": run_id,
                        "unit_index": index,
                        "unit_count": len(units),
                        "unit_key": unit_key,
                        "row_count": int(part["row_count"]),
                        "candidate_part_path": part["candidate_part_path"],
                    },
                )

            final_units = list(units_by_key.values())
            if any(str(row.get("status")) != "succeeded" for row in final_units):
                failed = len([row for row in final_units if str(row.get("status")) != "succeeded"])
                raise RuntimeError(f"仍有 {failed} 个 ComputeUnit 未成功，不能进入 compute_completed。")

            _flush_compute_checkpoint(
                manifest_root=manifest_root,
                units=final_units,
                candidate_parts=list(candidate_by_unit.values()),
                run_payload=run_payload,
                metrics={
                    "executed_unit_count": executed,
                    "skipped_unit_count": skipped,
                    "failed_unit_count": failed,
                    "candidate_part_count": len(candidate_by_unit),
                    "candidate_row_count": sum(int(row.get("row_count") or 0) for row in candidate_by_unit.values()),
                    "last_unit_index": len(units),
                    "unit_count": len(units),
                },
            )
            elapsed = time.perf_counter() - started
            run_payload = {
                **run_payload,
                "status": "compute_completed",
                "finished_at": _utc_now_iso(),
                "m2_finished_at": _utc_now_iso(),
                "m2_metrics": {
                    "executed_unit_count": executed,
                    "skipped_unit_count": skipped,
                    "failed_unit_count": failed,
                    "candidate_part_count": len(candidate_by_unit),
                    "candidate_row_count": sum(int(row.get("row_count") or 0) for row in candidate_by_unit.values()),
                    "elapsed_seconds": round(elapsed, 3),
                },
            }
            _write_json_atomic(manifest_root / "run.json", run_payload)
            _append_compute_event(
                manifest_root / "events.jsonl",
                {
                    "event_type": "candidate_compute_completed",
                    "level": "info",
                    "message": "M2 DuckDB candidate compute 完成；正式分区、gate、downstream queue 均未修改。",
                    "metrics": run_payload["m2_metrics"],
                },
            )
            return {
                "run_id": run_id,
                "status": "compute_completed",
                "manifest_root": _relpath(manifest_root, self.lake_root),
                "metrics": run_payload["m2_metrics"],
                "lock_acquired": lock_acquired,
                "lock_after": None,
                "formal_paths_touched": [],
            }
        finally:
            if connection is not None:
                connection.close()
            if lock_acquired is not None:
                lock_service.release(run_id=run_id)

    def _compute_unit_candidate(
        self,
        *,
        connection: Any,
        unit: dict[str, Any],
        latest_adj_paths: list[Path],
    ) -> dict[str, Any]:
        input_paths = json.loads(str(unit["input_paths_json"]))
        output_paths = json.loads(str(unit["output_paths_json"]))
        if len(output_paths) != 1:
            raise RuntimeError(f"ComputeUnit output_paths 必须只有一个 candidate part：{unit['unit_key']}")
        clean_paths = _resolve_existing_paths(self.lake_root, input_paths.get("clean_next") or [], label="clean_next")
        adj_paths = _resolve_existing_paths(self.lake_root, input_paths.get("adj_factor") or [], label="adj_factor")
        output_path = _resolve_candidate_output(self.lake_root, str(unit["run_id"]), str(output_paths[0]))
        metrics = connection.execute(
            _unit_metrics_sql(),
            [
                [str(path) for path in clean_paths],
                [str(path) for path in adj_paths],
                [str(path) for path in latest_adj_paths],
            ],
        ).fetchone()
        row_count = int(metrics[0] or 0)
        missing_adj = int(metrics[1] or 0)
        missing_latest = int(metrics[2] or 0)
        non_positive = int(metrics[3] or 0)
        if missing_adj or missing_latest or non_positive:
            raise RuntimeError(
                "qfq factor coverage 未通过："
                f"unit={unit['unit_key']} row_count={row_count} "
                f"missing_adj_factor_rows={missing_adj} "
                f"missing_latest_adj_factor_rows={missing_latest} "
                f"non_positive_factor_rows={non_positive}"
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_output = output_path.with_name(f".{output_path.name}.{os.getpid()}.{uuid4().hex}.tmp")
        if tmp_output.exists():
            tmp_output.unlink()
        connection.execute(
            _unit_copy_sql(tmp_output),
            [
                [str(path) for path in clean_paths],
                [str(path) for path in adj_paths],
                [str(path) for path in latest_adj_paths],
            ],
        )
        tmp_output.replace(output_path)
        return {
            "run_id": unit["run_id"],
            "unit_key": unit["unit_key"],
            "candidate_part_path": _relpath(output_path, self.lake_root),
            "row_count": row_count,
            "byte_count": output_path.stat().st_size,
            "checksum": _sha256_file(output_path),
            "status": "staged",
        }

    def _manifest_root(self, run_id: str) -> Path:
        return self.lake_root / "manifest" / "duckdb_compute" / "runs" / run_id


def _flush_compute_checkpoint(
    *,
    manifest_root: Path,
    units: list[dict[str, Any]],
    candidate_parts: list[dict[str, Any]],
    run_payload: dict[str, Any],
    metrics: dict[str, Any],
) -> None:
    checkpoint_at = _utc_now_iso()
    _write_units_manifest(manifest_root / "units.parquet", units)
    _write_candidate_parts_manifest(manifest_root / "candidate_parts.parquet", candidate_parts)
    _write_json_atomic(
        manifest_root / "run.json",
        {
            **run_payload,
            "m2_checkpoint": {
                "status": "running",
                "checkpoint_at": checkpoint_at,
                "metrics": metrics,
            },
        },
    )


def _unit_metrics_sql() -> str:
    return """
    with clean as (
        select
            ts_code,
            cast(freq as integer) as freq,
            cast(trade_time as timestamp) as trade_time,
            cast(trade_date as date) as trade_date,
            cast(open as double) as open,
            cast(high as double) as high,
            cast(low as double) as low,
            cast(close as double) as close,
            cast(vwap as double) as vwap,
            cast(vol as bigint) as vol,
            cast(amount as double) as amount
        from read_parquet(?, hive_partitioning=1)
    ),
    day_factor as (
        select
            ts_code,
            cast(trade_date as date) as trade_date,
            cast(adj_factor as double) as adj_factor
        from read_parquet(?, hive_partitioning=1)
    ),
    latest_factor as (
        select
            ts_code,
            cast(adj_factor as double) as latest_adj_factor
        from read_parquet(?, hive_partitioning=1)
    ),
    joined as (
        select clean.*, day_factor.adj_factor, latest_factor.latest_adj_factor
        from clean
        left join day_factor
          on clean.ts_code = day_factor.ts_code
         and clean.trade_date = day_factor.trade_date
        left join latest_factor
          on clean.ts_code = latest_factor.ts_code
    )
    select
        count(*) as row_count,
        sum(case when adj_factor is null then 1 else 0 end) as missing_adj_factor_rows,
        sum(case when latest_adj_factor is null then 1 else 0 end) as missing_latest_adj_factor_rows,
        sum(
            case
                when adj_factor is not null
                 and latest_adj_factor is not null
                 and (adj_factor <= 0 or latest_adj_factor <= 0)
                then 1
                else 0
            end
        ) as non_positive_factor_rows
    from joined
    """


def _unit_copy_sql(output_path: Path) -> str:
    return f"""
    copy (
        with clean as (
            select
                ts_code,
                cast(freq as integer) as freq,
                cast(trade_time as timestamp) as trade_time,
                cast(trade_date as date) as trade_date,
                cast(open as double) as open,
                cast(high as double) as high,
                cast(low as double) as low,
                cast(close as double) as close,
                cast(vwap as double) as vwap,
                cast(vol as bigint) as vol,
                cast(amount as double) as amount,
                cast(exchange as varchar) as exchange
            from read_parquet(?, hive_partitioning=1)
        ),
        day_factor as (
            select
                ts_code,
                cast(trade_date as date) as trade_date,
                cast(adj_factor as double) as adj_factor
            from read_parquet(?, hive_partitioning=1)
        ),
        latest_factor as (
            select
                ts_code,
                cast(adj_factor as double) as latest_adj_factor
            from read_parquet(?, hive_partitioning=1)
        )
        select
            clean.ts_code,
            clean.freq,
            clean.trade_time,
            clean.open * day_factor.adj_factor / latest_factor.latest_adj_factor as open,
            clean.high * day_factor.adj_factor / latest_factor.latest_adj_factor as high,
            clean.low * day_factor.adj_factor / latest_factor.latest_adj_factor as low,
            clean.close * day_factor.adj_factor / latest_factor.latest_adj_factor as close,
            clean.vol,
            clean.amount,
            clean.exchange,
            clean.vwap * day_factor.adj_factor / latest_factor.latest_adj_factor as vwap
        from clean
        join day_factor
          on clean.ts_code = day_factor.ts_code
         and clean.trade_date = day_factor.trade_date
        join latest_factor
          on clean.ts_code = latest_factor.ts_code
        order by clean.ts_code, clean.trade_time
    ) to {_sql_literal(str(output_path))} (format parquet, compression zstd)
    """


def _open_duckdb_connection(*, settings: LakeConsoleSettings, temp_dir: Path) -> Any:
    duckdb = _require_duckdb()
    connection = duckdb.connect(database=":memory:")
    connection.execute(f"PRAGMA threads={int(settings.duckdb_threads)}")
    connection.execute(f"PRAGMA memory_limit={_sql_literal(settings.duckdb_memory_limit)}")
    connection.execute(f"SET temp_directory={_sql_literal(str(temp_dir))}")
    return connection


def _read_manifest_rows(path: Path) -> list[dict[str, Any]]:
    try:
        import pandas as pd
        import pyarrow  # noqa: F401
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise RuntimeError("缺少 Parquet 读取依赖，请先安装 lake_console/backend/requirements.txt。") from exc
    if not path.exists():
        raise FileNotFoundError(f"缺少 run manifest 文件：{path}")
    frame = pd.read_parquet(path, engine="pyarrow")
    return [dict(row) for row in frame.to_dict(orient="records")]


def _write_units_manifest(path: Path, rows: list[dict[str, Any]]) -> None:
    _write_parquet_manifest(
        path,
        [_normalize_unit_row(row) for row in rows],
        columns=[
            "run_id",
            "unit_key",
            "continuity_key",
            "publish_partition_key",
            "input_paths_json",
            "output_paths_json",
            "duckdb_sql_template",
            "expected_output_role",
            "status",
            "error_code",
        ],
    )


def _write_candidate_parts_manifest(path: Path, rows: list[dict[str, Any]]) -> None:
    _write_parquet_manifest(
        path,
        [_normalize_candidate_row(row) for row in rows],
        columns=["run_id", "unit_key", "candidate_part_path", "row_count", "byte_count", "checksum", "status"],
    )


def _normalize_unit_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": row["run_id"],
        "unit_key": row["unit_key"],
        "continuity_key": row["continuity_key"],
        "publish_partition_key": row["publish_partition_key"],
        "input_paths_json": _ensure_json_text(row["input_paths_json"]),
        "output_paths_json": _ensure_json_text(row["output_paths_json"]),
        "duckdb_sql_template": row["duckdb_sql_template"],
        "expected_output_role": row["expected_output_role"],
        "status": row["status"],
        "error_code": row.get("error_code"),
    }


def _normalize_candidate_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": row["run_id"],
        "unit_key": row["unit_key"],
        "candidate_part_path": row["candidate_part_path"],
        "row_count": int(row.get("row_count") or 0),
        "byte_count": int(row.get("byte_count") or 0),
        "checksum": row.get("checksum"),
        "status": row["status"],
    }


def _candidate_is_complete(row: dict[str, Any] | None, lake_root: Path) -> bool:
    if not row or row.get("status") != "staged":
        return False
    rel_path = row.get("candidate_part_path")
    if not rel_path:
        return False
    return (lake_root / str(rel_path)).exists()


def _latest_adj_factor_paths(run_payload: dict[str, Any], lake_root: Path) -> list[Path]:
    source_items = run_payload.get("input_snapshot", {}).get("source_items") or []
    for item in source_items:
        if item.get("source_role") != "latest_adj_factor":
            continue
        files = item.get("files") or []
        paths = _resolve_existing_paths(lake_root, [file["path"] for file in files], label="latest_adj_factor")
        if paths:
            return paths
    raise RuntimeError("run input_snapshot 缺少 latest_adj_factor 文件，不能执行 qfq candidate compute。")


def _resolve_existing_paths(lake_root: Path, raw_paths: list[str], *, label: str) -> list[Path]:
    paths = [(lake_root / raw_path).resolve() for raw_path in raw_paths]
    missing = [path for path in paths if not path.exists()]
    if missing:
        preview = ", ".join(_relpath(path, lake_root) for path in missing[:5])
        raise FileNotFoundError(f"{label} 输入文件缺失：{preview}")
    for path in paths:
        _assert_inside_lake(path, lake_root, label=label)
    return paths


def _resolve_candidate_output(lake_root: Path, run_id: str, raw_path: str) -> Path:
    output_path = (lake_root / raw_path).resolve()
    allowed_root = (lake_root / "_tmp" / "duckdb_compute" / run_id / "candidate_parts").resolve()
    if output_path != allowed_root and allowed_root not in output_path.parents:
        raise RuntimeError(f"candidate 输出路径越界，拒绝写入：{raw_path}")
    return output_path


def _resolve_lake_relative_path(lake_root: Path, raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    resolved = path.resolve() if path.is_absolute() else (lake_root / path).resolve()
    _assert_inside_lake(resolved, lake_root, label="DuckDB temp")
    return resolved


def _assert_inside_lake(path: Path, lake_root: Path, *, label: str) -> None:
    resolved_root = lake_root.resolve()
    if path != resolved_root and resolved_root not in path.parents:
        raise RuntimeError(f"{label} 路径必须位于 Lake Root 内：{path}")


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON manifest 格式非法：{path}")
    return payload


def _append_compute_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    seq = 1
    if path.exists():
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                if line.strip():
                    seq = max(seq, int(json.loads(line).get("seq", 0)) + 1)
    payload = {
        "seq": seq,
        "created_at": _utc_now_iso(),
        **event,
    }
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str) + "\n")


def _ensure_json_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return _json_text(value)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _emit_progress(progress_callback: ProgressCallback | None, payload: dict[str, Any]) -> None:
    if progress_callback is not None:
        progress_callback(payload)


def _require_duckdb():  # type: ignore[no-untyped-def]
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("缺少 duckdb 依赖，请先安装 lake_console/backend/requirements.txt。") from exc
    return duckdb
