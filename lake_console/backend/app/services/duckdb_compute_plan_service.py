from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from lake_console.backend.app.services.lake_job_state import LakeJobLockService, LakeJobStateStore
from lake_console.backend.app.settings import LakeConsoleSettings


@dataclass(frozen=True)
class _PartitionInput:
    freq: int
    trade_date: date
    clean_root: Path
    clean_files: list[Path]
    adj_root: Path
    adj_files: list[Path]


class DuckDbComputePlanService:
    """Build read-only compute plans for DuckDB-backed large compute jobs."""

    def __init__(self, *, settings: LakeConsoleSettings) -> None:
        self.settings = settings
        self.lake_root = settings.lake_root.resolve()

    def plan_stk_mins_qfq(
        self,
        *,
        start_date: str,
        end_date: str,
        freqs: Iterable[int],
        run_id: str | None = None,
        plan_type: str = "stk_mins_qfq_dry_run",
    ) -> dict[str, Any]:
        range_start = _parse_date(start_date, label="start_date")
        range_end = _parse_date(end_date, label="end_date")
        if range_start > range_end:
            raise ValueError(f"start_date 不能晚于 end_date：{start_date} > {end_date}")
        selected_freqs = _normalize_freqs(freqs)
        effective_run_id = run_id or f"dryrun-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-stk-mins-qfq-{uuid4().hex[:6]}"
        effective_config = self._effective_config()
        config_hash = _sha256_json(effective_config)

        blockers: list[dict[str, Any]] = []
        partitions = self._collect_partitions(start=range_start, end=range_end, freqs=selected_freqs, blockers=blockers)
        latest_adj_root, latest_adj_files = _latest_partition_files(self.lake_root / "raw_tushare" / "adj_factor", "trade_date")
        identity_map_path = self.lake_root / "manifest" / "security_identity" / "security_identity_map.parquet"
        if latest_adj_root is None or not latest_adj_files:
            blockers.append(
                {
                    "code": "missing_latest_adj_factor_partition",
                    "message": "缺少 adj_factor 最新分区，无法计算前复权基准。",
                    "path": _relpath(self.lake_root / "raw_tushare" / "adj_factor", self.lake_root),
                }
            )
        if not identity_map_path.exists():
            blockers.append(
                {
                    "code": "missing_security_identity_map",
                    "message": "缺少 security_identity_map，无法确认股票代码归一化账本。",
                    "path": _relpath(identity_map_path, self.lake_root),
                }
            )

        units: list[dict[str, Any]] = []
        publish_partitions: list[dict[str, Any]] = []
        if not blockers:
            units, publish_partitions = self._build_compute_graph(run_id=effective_run_id, partitions=partitions)

        source_items = self._build_input_snapshot_items(
            partitions=partitions,
            latest_adj_root=latest_adj_root,
            latest_adj_files=latest_adj_files,
            identity_map_path=identity_map_path,
        )
        code_snapshot = _code_snapshot()
        input_snapshot = {
            "snapshot_id": _sha256_json(
                {
                    "source_items": source_items,
                    "code_version": code_snapshot,
                    "config_hash": config_hash,
                }
            ),
            "source_items": source_items,
            "code_version": code_snapshot,
            "config_hash": config_hash,
        }
        status = "blocked" if blockers else "planned"
        run = {
            "run_id": effective_run_id,
            "job_type": "stk_mins_qfq_clean_next",
            "dataset_key": "stk_mins",
            "status": status,
            "created_at": _utc_now_iso(),
            "finished_at": None,
            "input_range": {
                "start_date": range_start.isoformat(),
                "end_date": range_end.isoformat(),
                "freqs": selected_freqs,
            },
            "effective_config": effective_config,
            "input_snapshot": input_snapshot,
        }
        lock = LakeJobLockService(LakeJobStateStore(self.lake_root)).get_lock()
        return {
            "plan_type": plan_type,
            "run": run,
            "ready": not blockers,
            "blockers": blockers,
            "lock": lock,
            "metrics": {
                "partition_count": len(partitions),
                "unit_count": len(units),
                "publish_partition_count": len(publish_partitions),
                "expected_candidate_part_count": len(units),
            },
            "candidate_parts": [],
            "candidate_part_manifest": {
                "status": "not_created_in_dry_run",
                "expected_candidate_part_count": len(units),
                "message": "dry-run 只规划 candidate part 路径，不生成临时候选文件。",
            },
            "units": units,
            "publish_partitions": publish_partitions,
        }

    def prepare_stk_mins_qfq_run(self, *, start_date: str, end_date: str, freqs: Iterable[int]) -> dict[str, Any]:
        run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-stk-mins-qfq-{uuid4().hex[:6]}"
        plan = self.plan_stk_mins_qfq(
            start_date=start_date,
            end_date=end_date,
            freqs=freqs,
            run_id=run_id,
            plan_type="stk_mins_qfq_manifest_prepare",
        )
        if not plan["ready"]:
            return {
                **plan,
                "manifest": {
                    "persisted": False,
                    "manifest_root": None,
                    "message": "plan 存在阻断项，未持锁、未写 run manifest。",
                },
            }

        store = LakeJobStateStore(self.lake_root)
        lock_service = LakeJobLockService(store, stale_after_seconds=self.settings.compute_stale_heartbeat_seconds)
        lock_acquired: dict[str, Any] | None = None
        manifest: dict[str, Any] | None = None
        try:
            lock_acquired = lock_service.acquire(run_id=run_id, profile_key="duckdb_compute_stk_mins_qfq")
            manifest = self._write_run_manifest(plan=plan)
            lock_service.heartbeat(run_id=run_id)
        finally:
            if lock_acquired is not None:
                lock_service.release(run_id=run_id)
        return {
            **plan,
            "manifest": manifest,
            "lock_acquired": lock_acquired,
            "lock_after": lock_service.get_lock(),
        }

    def _write_run_manifest(self, *, plan: dict[str, Any]) -> dict[str, Any]:
        run_id = str(plan["run"]["run_id"])
        final_root = self.lake_root / "manifest" / "duckdb_compute" / "runs" / run_id
        tmp_root = self.lake_root / "manifest" / "duckdb_compute" / "_tmp" / run_id
        if final_root.exists():
            raise RuntimeError(f"run manifest 已存在，拒绝覆盖：{_relpath(final_root, self.lake_root)}")
        if tmp_root.exists():
            raise RuntimeError(f"run manifest 临时目录已存在，拒绝复用：{_relpath(tmp_root, self.lake_root)}")
        tmp_root.mkdir(parents=True, exist_ok=True)
        started_at = _utc_now_iso()
        run_payload = {
            **plan["run"],
            "manifest_root": _relpath(final_root, self.lake_root),
            "manifest_written_at": started_at,
            "blockers": plan["blockers"],
            "metrics": plan["metrics"],
        }
        _write_json_atomic(tmp_root / "run.json", run_payload)
        _write_parquet_manifest(
            tmp_root / "units.parquet",
            [_unit_manifest_row(unit) for unit in plan["units"]],
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
        _write_parquet_manifest(
            tmp_root / "candidate_parts.parquet",
            [],
            columns=["run_id", "unit_key", "candidate_part_path", "row_count", "byte_count", "checksum", "status"],
        )
        _write_parquet_manifest(
            tmp_root / "publish_partitions.parquet",
            [_publish_partition_manifest_row(partition) for partition in plan["publish_partitions"]],
            columns=[
                "run_id",
                "partition_key",
                "source_candidate_parts_json",
                "expected_candidate_part_paths_json",
                "expected_candidate_part_count",
                "target_path",
                "audit_status",
                "publish_status",
            ],
        )
        _append_event(
            tmp_root / "events.jsonl",
            {
                "event_type": "manifest_prepared",
                "level": "info",
                "message": "M1-B 已持锁写入 run manifest；未执行 DuckDB candidate 计算，未发布正式分区。",
                "metrics": plan["metrics"],
            },
        )
        final_root.parent.mkdir(parents=True, exist_ok=True)
        tmp_root.replace(final_root)
        try:
            tmp_root.parent.rmdir()
        except OSError:
            pass
        return {
            "persisted": True,
            "manifest_root": _relpath(final_root, self.lake_root),
            "files": {
                "run": _relpath(final_root / "run.json", self.lake_root),
                "units": _relpath(final_root / "units.parquet", self.lake_root),
                "candidate_parts": _relpath(final_root / "candidate_parts.parquet", self.lake_root),
                "publish_partitions": _relpath(final_root / "publish_partitions.parquet", self.lake_root),
                "events": _relpath(final_root / "events.jsonl", self.lake_root),
            },
            "message": "run manifest 已持久化；candidate_part 账本为空，正式数据未改动。",
        }

    def _collect_partitions(
        self, *, start: date, end: date, freqs: list[int], blockers: list[dict[str, Any]]
    ) -> list[_PartitionInput]:
        partitions: list[_PartitionInput] = []
        adj_root = self.lake_root / "raw_tushare" / "adj_factor"
        adj_by_date = _partition_file_map(adj_root, "trade_date", start, end)
        for freq in freqs:
            clean_freq_root = self.lake_root / "research" / "stk_mins_by_date_clean_next" / f"freq={freq}"
            clean_by_date = _partition_file_map(clean_freq_root, "trade_date", start, end)
            if not clean_by_date:
                blockers.append(
                    {
                        "code": "missing_clean_next_partition",
                        "message": f"指定范围内没有 clean_next 分区：freq={freq}",
                        "path": _relpath(clean_freq_root, self.lake_root),
                    }
                )
                continue
            for trade_date, clean_files in sorted(clean_by_date.items()):
                adj_files = adj_by_date.get(trade_date)
                if not adj_files:
                    blockers.append(
                        {
                            "code": "missing_adj_factor_partition",
                            "message": f"缺少同日 adj_factor 分区，无法计算 qfq：trade_date={trade_date.isoformat()}",
                            "path": _relpath(adj_root / f"trade_date={trade_date.isoformat()}", self.lake_root),
                            "freq": freq,
                            "trade_date": trade_date.isoformat(),
                        }
                    )
                    continue
                partitions.append(
                    _PartitionInput(
                        freq=freq,
                        trade_date=trade_date,
                        clean_root=clean_freq_root / f"trade_date={trade_date.isoformat()}",
                        clean_files=clean_files,
                        adj_root=adj_root / f"trade_date={trade_date.isoformat()}",
                        adj_files=adj_files,
                    )
                )
        return partitions

    def _build_compute_graph(
        self, *, run_id: str, partitions: list[_PartitionInput]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        units: list[dict[str, Any]] = []
        publish_partitions: list[dict[str, Any]] = []
        for partition in partitions:
            partition_key = f"freq={partition.freq}/trade_date={partition.trade_date.isoformat()}"
            target_path = self.lake_root / "research" / "stk_mins_by_date_clean_next" / partition_key
            expected_candidate_paths: list[str] = []
            for bucket in range(self.settings.compute_bucket_count):
                unit_key = f"{partition_key}/bucket={bucket:02d}"
                candidate_part_path = (
                    self.lake_root
                    / "_tmp"
                    / "duckdb_compute"
                    / run_id
                    / "candidate_parts"
                    / "research"
                    / "stk_mins_by_date_clean_next"
                    / partition_key
                    / f"bucket={bucket:02d}"
                    / "part-000.parquet"
                )
                expected_candidate_paths.append(_relpath(candidate_part_path, self.lake_root))
                units.append(
                    {
                        "run_id": run_id,
                        "unit_key": unit_key,
                        "continuity_key": f"freq={partition.freq}/bucket={bucket:02d}",
                        "publish_partition_key": partition_key,
                        "input_paths": {
                            "clean_next": [_relpath(path, self.lake_root) for path in partition.clean_files],
                            "adj_factor": [_relpath(path, self.lake_root) for path in partition.adj_files],
                        },
                        "output_paths": [_relpath(candidate_part_path, self.lake_root)],
                        "duckdb_sql_template": "stk_mins_qfq_by_partition_bucket_v1",
                        "expected_output_role": "qfq_candidate_part",
                        "status": "pending",
                        "error_code": None,
                    }
                )
            publish_partitions.append(
                {
                    "run_id": run_id,
                    "partition_key": partition_key,
                    "source_candidate_parts": [],
                    "expected_candidate_part_paths": expected_candidate_paths,
                    "expected_candidate_part_count": len(expected_candidate_paths),
                    "target_path": _relpath(target_path, self.lake_root),
                    "audit_status": "pending",
                    "publish_status": "pending",
                }
            )
        return units, publish_partitions

    def _build_input_snapshot_items(
        self,
        *,
        partitions: list[_PartitionInput],
        latest_adj_root: Path | None,
        latest_adj_files: list[Path],
        identity_map_path: Path,
    ) -> list[dict[str, Any]]:
        source_items: list[dict[str, Any]] = []
        seen_items: set[tuple[str, str]] = set()
        for partition in partitions:
            source_items.extend(
                self._deduped_source_items(
                    seen_items,
                    [
                        ("clean_next", partition.clean_root, partition.clean_files),
                        ("adj_factor", partition.adj_root, partition.adj_files),
                    ],
                )
            )
        if latest_adj_root is not None and latest_adj_files:
            source_items.extend(
                self._deduped_source_items(seen_items, [("latest_adj_factor", latest_adj_root, latest_adj_files)])
            )
        if identity_map_path.exists():
            source_items.extend(
                self._deduped_source_items(
                    seen_items, [("security_identity_map", identity_map_path, [identity_map_path])]
                )
            )
        return source_items

    def _deduped_source_items(
        self, seen_items: set[tuple[str, str]], candidates: list[tuple[str, Path, list[Path]]]
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for source_role, path, files in candidates:
            key = (source_role, _relpath(path, self.lake_root))
            if key in seen_items:
                continue
            seen_items.add(key)
            items.append(_source_item(source_role, path, files, self.lake_root))
        return items

    def _effective_config(self) -> dict[str, Any]:
        return {
            "duckdb_threads": self.settings.duckdb_threads,
            "duckdb_memory_limit": self.settings.duckdb_memory_limit,
            "duckdb_temp_directory": self.settings.duckdb_temp_directory,
            "compute_bucket_count": self.settings.compute_bucket_count,
            "compute_max_active_writers": self.settings.compute_max_active_writers,
            "compute_progress_interval_seconds": self.settings.compute_progress_interval_seconds,
            "compute_stale_heartbeat_seconds": self.settings.compute_stale_heartbeat_seconds,
            "compute_max_unit_retries": self.settings.compute_max_unit_retries,
        }


def _partition_file_map(root: Path, partition_key: str, start: date, end: date) -> dict[date, list[Path]]:
    if not root.exists():
        return {}
    prefix = f"{partition_key}="
    result: dict[date, list[Path]] = {}
    for partition in root.glob(f"{prefix}*"):
        if not partition.is_dir() or not partition.name.startswith(prefix):
            continue
        try:
            partition_date = date.fromisoformat(partition.name.removeprefix(prefix))
        except ValueError:
            continue
        if start <= partition_date <= end:
            files = sorted(path for path in partition.glob("*.parquet") if path.is_file())
            if files:
                result[partition_date] = files
    return result


def _latest_partition_files(root: Path, partition_key: str) -> tuple[Path | None, list[Path]]:
    if not root.exists():
        return None, []
    prefix = f"{partition_key}="
    latest: tuple[date, Path] | None = None
    for partition in root.glob(f"{prefix}*"):
        if not partition.is_dir() or not partition.name.startswith(prefix):
            continue
        try:
            partition_date = date.fromisoformat(partition.name.removeprefix(prefix))
        except ValueError:
            continue
        if latest is None or partition_date > latest[0]:
            latest = (partition_date, partition)
    if latest is None:
        return None, []
    return latest[1], sorted(path for path in latest[1].glob("*.parquet") if path.is_file())


def _source_item(source_role: str, path: Path, files: list[Path], lake_root: Path) -> dict[str, Any]:
    file_items = [_parquet_file_item(file, lake_root) for file in sorted(files)]
    schema_fingerprints = sorted({item["schema_fingerprint"] for item in file_items if item["schema_fingerprint"]})
    row_count = sum(int(item["row_count"] or 0) for item in file_items)
    byte_count = sum(int(item["byte_count"] or 0) for item in file_items)
    metadata_signature = _sha256_json(file_items)
    return {
        "source_role": source_role,
        "path": _relpath(path, lake_root),
        "file_count": len(file_items),
        "row_count": row_count,
        "byte_count": byte_count,
        "schema_fingerprint": _sha256_json(schema_fingerprints) if schema_fingerprints else None,
        "metadata_signature": metadata_signature,
        "files": file_items,
    }


def _parquet_file_item(path: Path, lake_root: Path) -> dict[str, Any]:
    stat = path.stat()
    parquet = _read_parquet_metadata(path)
    payload = {
        "path": _relpath(path, lake_root),
        "byte_count": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "row_count": parquet["row_count"],
        "schema_fingerprint": parquet["schema_fingerprint"],
    }
    payload["metadata_signature"] = _sha256_json(payload)
    return payload


def _read_parquet_metadata(path: Path) -> dict[str, Any]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("缺少 pyarrow 依赖，无法读取 Parquet metadata。") from exc
    parquet_file = pq.ParquetFile(path)
    schema_text = str(parquet_file.schema_arrow)
    return {
        "row_count": int(parquet_file.metadata.num_rows),
        "schema_fingerprint": hashlib.sha256(schema_text.encode("utf-8")).hexdigest(),
    }


def _unit_manifest_row(unit: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": unit["run_id"],
        "unit_key": unit["unit_key"],
        "continuity_key": unit["continuity_key"],
        "publish_partition_key": unit["publish_partition_key"],
        "input_paths_json": _json_text(unit["input_paths"]),
        "output_paths_json": _json_text(unit["output_paths"]),
        "duckdb_sql_template": unit["duckdb_sql_template"],
        "expected_output_role": unit["expected_output_role"],
        "status": unit["status"],
        "error_code": unit["error_code"],
    }


def _publish_partition_manifest_row(partition: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": partition["run_id"],
        "partition_key": partition["partition_key"],
        "source_candidate_parts_json": _json_text(partition["source_candidate_parts"]),
        "expected_candidate_part_paths_json": _json_text(partition["expected_candidate_part_paths"]),
        "expected_candidate_part_count": partition["expected_candidate_part_count"],
        "target_path": partition["target_path"],
        "audit_status": partition["audit_status"],
        "publish_status": partition["publish_status"],
    }


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    with tmp_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, sort_keys=True, indent=2, default=str)
        file.write("\n")
    _replace_with_retry(tmp_path, path)


def _write_parquet_manifest(path: Path, rows: list[dict[str, Any]], *, columns: list[str]) -> None:
    try:
        import pandas as pd
        import pyarrow  # noqa: F401
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise RuntimeError("缺少 Parquet 写入依赖，请先安装 lake_console/backend/requirements.txt。") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    frame = pd.DataFrame(rows, columns=columns)
    frame.to_parquet(tmp_path, index=False, engine="pyarrow", compression="zstd")
    _replace_with_retry(tmp_path, path)


def _replace_with_retry(tmp_path: Path, path: Path, *, attempts: int = 3) -> None:
    for attempt in range(1, attempts + 1):
        try:
            tmp_path.replace(path)
            return
        except FileNotFoundError:
            if attempt >= attempts or not tmp_path.exists():
                raise
            time.sleep(0.2 * attempt)


def _append_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "seq": 1,
        "created_at": _utc_now_iso(),
        **event,
    }
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str) + "\n")


def _code_snapshot() -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[4]
    commit = _run_git(repo_root, ["rev-parse", "HEAD"])
    dirty = _run_git(repo_root, ["status", "--porcelain"])
    return {
        "commit": commit or "unknown",
        "worktree_dirty": bool(dirty),
    }


def _run_git(cwd: Path, args: list[str]) -> str | None:
    try:
        result = subprocess.run(["git", *args], cwd=cwd, check=False, capture_output=True, text=True, timeout=5)
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _normalize_freqs(freqs: Iterable[int]) -> list[int]:
    values = list(dict.fromkeys(int(item) for item in freqs))
    allowed = {1, 5, 15, 30, 60}
    invalid = sorted(set(values) - allowed)
    if invalid:
        raise ValueError(f"不支持的 freqs={invalid}，允许值：1,5,15,30,60")
    if not values:
        raise ValueError("freqs 不能为空。")
    return values


def _parse_date(raw_value: str, *, label: str) -> date:
    try:
        return date.fromisoformat(raw_value)
    except ValueError as exc:
        raise ValueError(f"{label} 必须是 YYYY-MM-DD：{raw_value}") from exc


def _relpath(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve()))


def _sha256_json(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_text(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
