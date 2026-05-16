from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Callable

from lake_console.backend.app.services.downstream_rebuild_requirement_service import (
    DOWNSTREAM_REBUILD_REQUIREMENT_RELATIVE_PATH,
    DownstreamRebuildRequirementService,
)
from lake_console.backend.app.services.duckdb_compute_audit_service import _read_manifest_rows
from lake_console.backend.app.services.duckdb_compute_plan_service import _relpath, _utc_now_iso, _write_json_atomic
from lake_console.backend.app.services.lake_job_state import LakeJobLockService, LakeJobStateStore
from lake_console.backend.app.services.stk_mins_clean_next_gate import (
    CLEAN_NEXT_GATE_RELATIVE_PATH,
    CLEAN_NEXT_GATE_SCHEMA_VERSION,
    CleanNextPartitionGateService,
)
from lake_console.backend.app.settings import LakeConsoleSettings


ProgressCallback = Callable[[dict[str, Any]], None]
GATE_PUBLISH_PLAN_FILENAME = "gate_publish_plan.json"


class DuckDbComputePublishService:
    """Preflight the formal publish stage for DuckDB compute runs.

    M3-C-A is intentionally read-only: this service validates the release plan
    and builds the planned gate/downstream rows, but it does not replace formal
    partitions, write clean_next gate rows, or write downstream queues.
    """

    def __init__(self, *, settings: LakeConsoleSettings) -> None:
        self.settings = settings
        self.lake_root = settings.lake_root.resolve()

    def preflight_stk_mins_qfq_publish(
        self,
        *,
        run_id: str,
        progress_callback: ProgressCallback | None = None,
        allow_lock_run_id: str | None = None,
    ) -> dict[str, Any]:
        manifest_root = self._manifest_root(run_id)
        blockers: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        target_partitions: list[dict[str, Any]] = []
        gate_plan: list[dict[str, Any]] = []

        if not manifest_root.exists():
            raise FileNotFoundError(f"未找到 DuckDB compute run manifest：{_relpath(manifest_root, self.lake_root)}")

        run_payload = _read_json(manifest_root / "run.json")
        self._validate_run_payload(run_payload=run_payload, blockers=blockers)
        self._validate_prewrite_backup(manifest_root=manifest_root, run_payload=run_payload, blockers=blockers)
        self._validate_audit_ledger(manifest_root=manifest_root, blockers=blockers)

        publish_rows = self._read_publish_rows(manifest_root=manifest_root, blockers=blockers)
        gate_rows = {str(row.get("partition_key") or ""): row for row in CleanNextPartitionGateService(lake_root=self.lake_root).read_statuses()}

        for index, row in enumerate(publish_rows, start=1):
            _emit_progress(
                progress_callback,
                {
                    "event": "publish_partition_preflight",
                    "run_id": run_id,
                    "partition_index": index,
                    "partition_count": len(publish_rows),
                    "partition_key": row.get("partition_key"),
                },
            )
            partition_summary = self._preflight_publish_partition(row=row, run_id=run_id, blockers=blockers, warnings=warnings)
            target_partitions.append(partition_summary)
            current_gate = gate_rows.get(str(row.get("partition_key") or ""))
            gate_plan.append(
                {
                    "partition_key": row.get("partition_key"),
                    "current_status": current_gate.get("status") if current_gate else None,
                    "current_write_revision": current_gate.get("write_revision") if current_gate else None,
                    "planned_before_replace": "publishing",
                    "planned_after_downstream": "passed",
                    "write_intent": False,
                }
            )

        lock = LakeJobLockService(LakeJobStateStore(self.lake_root), stale_after_seconds=self.settings.compute_stale_heartbeat_seconds).get_lock()
        if lock.get("status") != "idle" and str(lock.get("run_id") or "") != str(allow_lock_run_id or ""):
            blockers.append(
                {
                    "code": "lake_write_lock_not_idle",
                    "message": "当前 Lake 写入锁不是 idle，正式发布前必须等待其它写任务结束。",
                    "actual": lock,
                }
            )

        downstream_requirements: list[dict[str, Any]] = []
        if publish_rows:
            try:
                downstream_requirements = DownstreamRebuildRequirementService(lake_root=self.lake_root).build_stk_mins_qfq_requirements(
                    source_publish_id=run_id,
                    publish_partitions=publish_rows,
                )
            except ValueError as exc:
                blockers.append(
                    {
                        "code": "downstream_requirement_plan_failed",
                        "message": "无法根据 publish_partitions 生成 downstream requirement 计划。",
                        "technical_detail": str(exc),
                    }
                )

        ready = not blockers
        return {
            "operation": "preflight_stk_mins_qfq_publish",
            "stage": "m3c_a_preflight",
            "run_id": run_id,
            "status": "ready" if ready else "blocked",
            "ready": ready,
            "write_intent": False,
            "formal_paths_touched": [],
            "manifest_root": _relpath(manifest_root, self.lake_root),
            "blockers": blockers,
            "warnings": warnings,
            "lock": lock,
            "metrics": {
                "publish_partition_count": len(publish_rows),
                "target_partition_count": len(target_partitions),
                "candidate_part_count": sum(int(item["candidate_part_count"]) for item in target_partitions),
                "candidate_row_count": sum(int(item["candidate_row_count"]) for item in target_partitions),
                "gate_plan_count": len(gate_plan),
                "downstream_requirement_count": len(downstream_requirements),
            },
            "prewrite_backup": _safe_read_json(manifest_root / "prewrite_backup.json"),
            "target_partitions": target_partitions,
            "gate_plan": gate_plan,
            "downstream_requirement_file": _relpath(self.lake_root / DOWNSTREAM_REBUILD_REQUIREMENT_RELATIVE_PATH, self.lake_root),
            "downstream_requirements": downstream_requirements,
            "message": (
                "M3-C-A preflight 通过；下一阶段才允许进入正式 publishing。"
                if ready
                else "M3-C-A preflight 未通过；正式 clean_next 未被修改。"
            ),
        }

    def prepare_stk_mins_qfq_gate_publish_plan(
        self,
        *,
        run_id: str,
        progress_callback: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        """Persist the M3-C-B publishing gate plan under the run manifest only.

        This stage intentionally does not write the formal clean_next gate or
        replace any formal partition. The actual formal gate must be written
        inside the later publish transaction, immediately before atomic replace.
        """

        manifest_root = self._manifest_root(run_id)
        if not manifest_root.exists():
            raise FileNotFoundError(f"未找到 DuckDB compute run manifest：{_relpath(manifest_root, self.lake_root)}")

        store = LakeJobStateStore(self.lake_root)
        lock_service = LakeJobLockService(store, stale_after_seconds=self.settings.compute_stale_heartbeat_seconds)
        lock_acquired: dict[str, Any] | None = None
        try:
            lock_acquired = lock_service.acquire(run_id=run_id, profile_key="duckdb_compute_stk_mins_qfq")
            _emit_progress(progress_callback, {"event": "gate_publish_plan_started", "run_id": run_id})
            preflight = self.preflight_stk_mins_qfq_publish(
                run_id=run_id,
                progress_callback=progress_callback,
                allow_lock_run_id=run_id,
            )
            if not preflight["ready"]:
                return {
                    "operation": "prepare_stk_mins_qfq_gate_publish_plan",
                    "stage": "m3c_b_gate_publish_plan",
                    "run_id": run_id,
                    "status": "blocked",
                    "ready": False,
                    "write_intent": False,
                    "formal_write_intent": False,
                    "formal_paths_touched": [],
                    "manifest_root": _relpath(manifest_root, self.lake_root),
                    "preflight": preflight,
                    "message": "M3-C-B gate publishing 计划未写入；preflight 仍存在阻断项。",
                    "lock_acquired": lock_acquired,
                    "lock_after": None,
                }

            plan_file = manifest_root / GATE_PUBLISH_PLAN_FILENAME
            if plan_file.exists():
                existing_plan = _read_json(plan_file)
                run_payload = _read_json(manifest_root / "run.json")
                expected_state = _gate_publish_plan_run_state(
                    plan_file=plan_file,
                    lake_root=self.lake_root,
                    planned_gate_row_count=int((existing_plan.get("metrics") or {}).get("planned_gate_row_count") or 0),
                )
                state_repaired = False
                current_state = run_payload.get("m3c_b_gate_publish_plan") or {}
                if current_state.get("status") != "success" or current_state.get("record_path") != expected_state["record_path"]:
                    _write_json_atomic(
                        manifest_root / "run.json",
                        {
                            **run_payload,
                            "status": "prewrite_backup",
                            "m3c_b_gate_publish_plan": expected_state,
                            "finished_at": None,
                            "error": None,
                        },
                    )
                    _append_publish_event(
                        manifest_root / "events.jsonl",
                        {
                            "event_type": "gate_publish_plan_state_repaired",
                            "level": "info",
                            "message": "M3-C-B gate publishing 计划文件已存在，本次补齐 run.json 阶段状态；未写 formal gate，未替换正式分区。",
                            "metrics": existing_plan.get("metrics") or {},
                        },
                    )
                    state_repaired = True
                lock_service.heartbeat(run_id=run_id)
                return {
                    "operation": "prepare_stk_mins_qfq_gate_publish_plan",
                    "stage": "m3c_b_gate_publish_plan",
                    "run_id": run_id,
                    "status": "gate_publish_plan_prepared",
                    "ready": True,
                    "idempotent": True,
                    "write_intent": state_repaired,
                    "formal_write_intent": False,
                    "run_manifest_write_intent": state_repaired,
                    "formal_paths_touched": [],
                    "manifest_root": _relpath(manifest_root, self.lake_root),
                    "gate_publish_plan": _relpath(plan_file, self.lake_root),
                    "metrics": existing_plan.get("metrics") or {},
                    "message": (
                        "M3-C-B gate publishing 计划已存在，本次补齐 run.json 状态；正式数据未被修改。"
                        if state_repaired
                        else "M3-C-B gate publishing 计划已存在，本次未重复写入。"
                    ),
                    "lock_acquired": lock_acquired,
                    "lock_after": None,
                }

            planned_gate_rows = [
                _planned_gate_row(run_id=run_id, partition=partition)
                for partition in preflight["target_partitions"]
            ]
            plan_payload = {
                "plan_schema_version": 1,
                "stage": "m3c_b_gate_publish_plan",
                "publish_mode": "layer_cutover_publish",
                "run_id": run_id,
                "created_at": _utc_now_iso(),
                "formal_gate_file": _relpath(self.lake_root / CLEAN_NEXT_GATE_RELATIVE_PATH, self.lake_root),
                "formal_write_intent": False,
                "run_manifest_write_intent": True,
                "message": "本文件只是正式 gate publishing 写入计划；尚未写 formal gate，尚未替换正式分区。",
                "preflight_status": preflight["status"],
                "metrics": {
                    "planned_gate_row_count": len(planned_gate_rows),
                    "target_partition_count": len(preflight["target_partitions"]),
                    "downstream_requirement_count": len(preflight["downstream_requirements"]),
                    "candidate_row_count": preflight["metrics"]["candidate_row_count"],
                    "candidate_part_count": preflight["metrics"]["candidate_part_count"],
                },
                "gate_rows": planned_gate_rows,
                "target_partitions": preflight["target_partitions"],
                "downstream_requirements": preflight["downstream_requirements"],
            }
            _write_json_atomic(plan_file, plan_payload)

            run_payload = _read_json(manifest_root / "run.json")
            run_payload = {
                **run_payload,
                "status": "prewrite_backup",
                "m3c_b_gate_publish_plan": _gate_publish_plan_run_state(
                    plan_file=plan_file,
                    lake_root=self.lake_root,
                    planned_gate_row_count=len(planned_gate_rows),
                ),
                "finished_at": None,
                "error": None,
            }
            _write_json_atomic(manifest_root / "run.json", run_payload)
            _append_publish_event(
                manifest_root / "events.jsonl",
                {
                    "event_type": "gate_publish_plan_prepared",
                    "level": "info",
                    "message": "M3-C-B 已持锁写入 gate publishing 计划；未写 formal gate，未替换正式分区。",
                    "metrics": plan_payload["metrics"],
                },
            )
            lock_service.heartbeat(run_id=run_id)
            _emit_progress(
                progress_callback,
                {
                    "event": "gate_publish_plan_completed",
                    "run_id": run_id,
                    "planned_gate_row_count": len(planned_gate_rows),
                },
            )
            return {
                "operation": "prepare_stk_mins_qfq_gate_publish_plan",
                "stage": "m3c_b_gate_publish_plan",
                "run_id": run_id,
                "status": "gate_publish_plan_prepared",
                "ready": True,
                "write_intent": True,
                "formal_write_intent": False,
                "run_manifest_write_intent": True,
                "formal_paths_touched": [],
                "manifest_root": _relpath(manifest_root, self.lake_root),
                "gate_publish_plan": _relpath(plan_file, self.lake_root),
                "metrics": plan_payload["metrics"],
                "message": "M3-C-B gate publishing 计划已写入 run manifest；正式数据和 formal gate 未被修改。",
                "lock_acquired": lock_acquired,
                "lock_after": None,
            }
        finally:
            if lock_acquired is not None:
                lock_service.release(run_id=run_id)

    def _validate_run_payload(self, *, run_payload: dict[str, Any], blockers: list[dict[str, Any]]) -> None:
        if run_payload.get("job_type") != "stk_mins_qfq_clean_next":
            blockers.append(
                {
                    "code": "unsupported_job_type",
                    "message": "当前 run 不是 stk_mins qfq clean_next 发布任务。",
                    "actual": run_payload.get("job_type"),
                }
            )
        if run_payload.get("status") != "prewrite_backup":
            blockers.append(
                {
                    "code": "run_not_after_prewrite_backup",
                    "message": "当前 run 未停在 prewrite_backup，不能进入 M3-C 发布预检。",
                    "actual": run_payload.get("status"),
                }
            )
        backup_state = run_payload.get("m3b_prewrite_backup") or {}
        if backup_state.get("status") != "success":
            blockers.append(
                {
                    "code": "m3b_prewrite_backup_missing",
                    "message": "run.json 中缺少成功的 M3-B 写前备份状态。",
                    "actual": backup_state,
                }
            )

    def _validate_prewrite_backup(self, *, manifest_root: Path, run_payload: dict[str, Any], blockers: list[dict[str, Any]]) -> None:
        backup_file = manifest_root / "prewrite_backup.json"
        backup = _safe_read_json(backup_file)
        if backup is None:
            blockers.append(
                {
                    "code": "prewrite_backup_file_missing",
                    "message": "缺少 prewrite_backup.json，不能进入正式发布。",
                    "path": _relpath(backup_file, self.lake_root),
                }
            )
            return
        if backup.get("status") != "success":
            blockers.append(
                {
                    "code": "prewrite_backup_not_success",
                    "message": "prewrite_backup.json 不是 success 状态。",
                    "actual": backup.get("status"),
                }
            )
        if not backup.get("snapshot_ids"):
            blockers.append({"code": "prewrite_backup_missing_snapshot_ids", "message": "写前备份缺少 snapshot_ids。"})
        snapshot_paths = set(str(path) for path in backup.get("snapshot_paths") or [])
        if "research/stk_mins_by_date_clean_next" not in snapshot_paths or "manifest" not in snapshot_paths:
            blockers.append(
                {
                    "code": "prewrite_backup_snapshot_scope_invalid",
                    "message": "写前备份没有覆盖正式 clean_next 根路径和 manifest 根路径。",
                    "actual": sorted(snapshot_paths),
                }
            )
        record_path = ((run_payload.get("m3b_prewrite_backup") or {}).get("record_path") or "")
        if record_path and not (self.lake_root / str(record_path)).exists():
            blockers.append(
                {
                    "code": "prewrite_backup_record_missing",
                    "message": "run.json 中记录的写前备份文件不存在。",
                    "path": record_path,
                }
            )

    def _validate_audit_ledger(self, *, manifest_root: Path, blockers: list[dict[str, Any]]) -> None:
        audit_file = manifest_root / "audit_ledger.parquet"
        if not audit_file.exists():
            blockers.append(
                {
                    "code": "candidate_audit_ledger_missing",
                    "message": "缺少 candidate audit ledger，不能进入发布预检。",
                    "path": _relpath(audit_file, self.lake_root),
                }
            )
            return
        issue_rows = _read_manifest_rows(audit_file)
        if issue_rows:
            blockers.append(
                {
                    "code": "candidate_audit_has_open_issues",
                    "message": "candidate audit ledger 仍有问题，不能进入正式发布。",
                    "actual": {"issue_count": len(issue_rows)},
                }
            )

    def _read_publish_rows(self, *, manifest_root: Path, blockers: list[dict[str, Any]]) -> list[dict[str, Any]]:
        publish_file = manifest_root / "publish_partitions.parquet"
        if not publish_file.exists():
            blockers.append(
                {
                    "code": "publish_partitions_missing",
                    "message": "缺少 publish_partitions.parquet，不能进入发布预检。",
                    "path": _relpath(publish_file, self.lake_root),
                }
            )
            return []
        rows = _read_manifest_rows(publish_file)
        if not rows:
            blockers.append({"code": "publish_partitions_empty", "message": "publish_partitions 为空。"})
        bad_rows = [
            row
            for row in rows
            if str(row.get("audit_status") or "") != "passed" or str(row.get("publish_status") or "") != "audit_passed"
        ]
        if bad_rows:
            blockers.append(
                {
                    "code": "publish_partitions_not_audit_passed",
                    "message": "仍有发布分区未通过 candidate audit。",
                    "actual": [row.get("partition_key") for row in bad_rows[:10]],
                }
            )
        return rows

    def _preflight_publish_partition(
        self,
        *,
        row: dict[str, Any],
        run_id: str,
        blockers: list[dict[str, Any]],
        warnings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        partition_key = str(row.get("partition_key") or "")
        try:
            _parse_partition_key(partition_key)
        except ValueError as exc:
            blockers.append(
                {
                    "code": "publish_partition_key_invalid",
                    "message": "发布分区 partition_key 格式非法。",
                    "partition_key": partition_key,
                    "technical_detail": str(exc),
                }
            )
        target_path = str(row.get("target_path") or "")
        if not target_path:
            blockers.append(
                {
                    "code": "target_path_missing",
                    "message": "发布分区缺少 target_path。",
                    "partition_key": partition_key,
                }
            )
            target_path = "."
        target_absolute = _resolve_lake_path(self.lake_root, target_path)
        clean_root = (self.lake_root / "research" / "stk_mins_by_date_clean_next").resolve()
        if target_absolute != clean_root and clean_root not in target_absolute.parents:
            blockers.append(
                {
                    "code": "target_path_outside_clean_next",
                    "message": "目标正式路径不在 research/stk_mins_by_date_clean_next 下。",
                    "partition_key": partition_key,
                    "target_path": target_path,
                }
            )

        candidate_paths = _json_array(row.get("source_candidate_parts_json"))
        if not candidate_paths:
            blockers.append(
                {
                    "code": "source_candidate_parts_empty",
                    "message": "发布分区缺少通过审计后的 source_candidate_parts。",
                    "partition_key": partition_key,
                }
            )
        expected_count = int(row.get("expected_candidate_part_count") or 0)
        if candidate_paths and len(candidate_paths) != expected_count:
            blockers.append(
                {
                    "code": "candidate_part_count_mismatch",
                    "message": "source_candidate_parts 数量与 expected_candidate_part_count 不一致。",
                    "partition_key": partition_key,
                    "expected": expected_count,
                    "actual": len(candidate_paths),
                }
            )

        candidate_row_count = 0
        candidate_byte_count = 0
        missing_candidate_paths: list[str] = []
        for raw_path in candidate_paths:
            candidate_path = _resolve_candidate_path(self.lake_root, run_id, str(raw_path))
            if not candidate_path.exists():
                missing_candidate_paths.append(str(raw_path))
                continue
            metadata = _parquet_metadata(candidate_path)
            candidate_row_count += int(metadata["row_count"])
            candidate_byte_count += int(candidate_path.stat().st_size)
        if missing_candidate_paths:
            blockers.append(
                {
                    "code": "candidate_part_file_missing",
                    "message": "发布分区存在缺失的 candidate_part 文件。",
                    "partition_key": partition_key,
                    "paths": missing_candidate_paths[:10],
                }
            )
        if candidate_paths and candidate_row_count == 0:
            warnings.append(
                {
                    "code": "candidate_partition_zero_rows",
                    "message": "发布分区 candidate 行数为 0，请确认是否符合预期。",
                    "partition_key": partition_key,
                }
            )

        return {
            "partition_key": partition_key,
            "target_path": target_path,
            "target_exists": target_absolute.exists(),
            "audit_status": row.get("audit_status"),
            "publish_status": row.get("publish_status"),
            "candidate_part_count": len(candidate_paths),
            "candidate_row_count": candidate_row_count,
            "candidate_byte_count": candidate_byte_count,
            "planned_publish_status": "publishing",
            "write_intent": False,
        }

    def _manifest_root(self, run_id: str) -> Path:
        return self.lake_root / "manifest" / "duckdb_compute" / "runs" / run_id


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON manifest 格式非法：{path}")
    return payload


def _safe_read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return _read_json(path)


def _json_array(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    text = str(value)
    if not text or text.lower() == "nan":
        return []
    payload = json.loads(text)
    if not isinstance(payload, list):
        raise ValueError(f"JSON 字段不是数组：{text[:120]}")
    return payload


def _parse_partition_key(partition_key: str) -> dict[str, Any]:
    parts = {}
    for item in partition_key.split("/"):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        parts[key] = value
    try:
        return {"freq": int(parts["freq"]), "trade_date": date.fromisoformat(parts["trade_date"])}
    except (KeyError, ValueError) as exc:
        raise ValueError(f"publish partition_key 格式非法：{partition_key}") from exc


def _resolve_lake_path(lake_root: Path, raw_path: str) -> Path:
    path = (lake_root / raw_path).resolve()
    if path != lake_root and lake_root not in path.parents:
        raise RuntimeError(f"Lake 路径越界：{raw_path}")
    return path


def _resolve_candidate_path(lake_root: Path, run_id: str, raw_path: str) -> Path:
    path = _resolve_lake_path(lake_root, raw_path)
    allowed_root = (lake_root / "_tmp" / "duckdb_compute" / run_id / "candidate_parts").resolve()
    if path != allowed_root and allowed_root not in path.parents:
        raise RuntimeError(f"candidate_part 路径越界：{raw_path}")
    return path


def _parquet_metadata(path: Path) -> dict[str, Any]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("缺少 pyarrow 依赖，无法读取 Parquet metadata。") from exc
    parquet_file = pq.ParquetFile(path)
    return {"row_count": int(parquet_file.metadata.num_rows)}


def _emit_progress(callback: ProgressCallback | None, event: dict[str, Any]) -> None:
    if callback is not None:
        callback(event)


def _planned_gate_row(*, run_id: str, partition: dict[str, Any]) -> dict[str, Any]:
    parsed = _parse_partition_key(str(partition["partition_key"]))
    return {
        "gate_schema_version": CLEAN_NEXT_GATE_SCHEMA_VERSION,
        "dataset_key": "stk_mins",
        "source_key": "tushare",
        "freq": parsed["freq"],
        "trade_date": parsed["trade_date"].isoformat(),
        "partition_key": partition["partition_key"],
        "clean_partition_path": partition["target_path"],
        "source_run_id": run_id,
        "clean_run_id": run_id,
        "write_revision": f"{run_id}:qfq:{partition['partition_key']}",
        "status": "publishing",
        "issue_count": 0,
        "raw_rows": int(partition.get("candidate_row_count") or 0),
        "clean_rows": int(partition.get("candidate_row_count") or 0),
        "checked_at": None,
        "ledger_path": f"manifest/duckdb_compute/runs/{run_id}/formal_audit_ledger.parquet",
        "message": "计划在正式 replace 前写入 publishing，用于阻断下游消费。",
    }


def _gate_publish_plan_run_state(*, plan_file: Path, lake_root: Path, planned_gate_row_count: int) -> dict[str, Any]:
    return {
        "status": "success",
        "finished_at": _utc_now_iso(),
        "record_path": _relpath(plan_file, lake_root),
        "planned_gate_row_count": planned_gate_row_count,
        "formal_gate_written": False,
        "formal_paths_touched": [],
    }


def _append_publish_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    seq = 1
    if path.exists():
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                if line.strip():
                    seq = max(seq, int(json.loads(line).get("seq", 0)) + 1)
    payload = {"seq": seq, "created_at": _utc_now_iso(), **event}
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str) + "\n")
