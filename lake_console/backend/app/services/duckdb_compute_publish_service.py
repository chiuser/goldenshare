from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path
from typing import Any, Callable

from lake_console.backend.app.services.downstream_rebuild_requirement_service import (
    DOWNSTREAM_REBUILD_REQUIREMENT_RELATIVE_PATH,
    DownstreamRebuildRequirementService,
)
from lake_console.backend.app.services.duckdb_compute_audit_service import EXPECTED_QFQ_CANDIDATE_COLUMNS, _read_manifest_rows
from lake_console.backend.app.services.duckdb_compute_plan_service import _json_text, _relpath, _utc_now_iso, _write_json_atomic, _write_parquet_manifest
from lake_console.backend.app.services.indicators import IndicatorRecalcQueueService
from lake_console.backend.app.services.lake_job_state import LakeJobLockService, LakeJobStateStore
from lake_console.backend.app.services.parquet_writer import replace_directory_atomically
from lake_console.backend.app.services.stk_mins_clean_next_gate import (
    CLEAN_NEXT_GATE_RELATIVE_PATH,
    CLEAN_NEXT_GATE_SCHEMA_VERSION,
    CleanNextGateStatus,
    CleanNextPartitionGateService,
)
from lake_console.backend.app.settings import LakeConsoleSettings


ProgressCallback = Callable[[dict[str, Any]], None]
GATE_PUBLISH_PLAN_FILENAME = "gate_publish_plan.json"
PUBLISH_PARTITION_COLUMNS = [
    "run_id",
    "partition_key",
    "source_candidate_parts_json",
    "expected_candidate_part_paths_json",
    "expected_candidate_part_count",
    "target_path",
    "audit_status",
    "publish_status",
]
FORMAL_AUDIT_LEDGER_FILENAME = "formal_audit_ledger.parquet"
FORMAL_AUDIT_LEDGER_COLUMNS = [
    "run_id",
    "partition_key",
    "issue_code",
    "severity",
    "target_path",
    "message",
    "expected_value",
    "actual_value",
    "observed_at",
]


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
        allowed_publish_statuses: set[str] | None = None,
        allowed_run_statuses: set[str] | None = None,
    ) -> dict[str, Any]:
        manifest_root = self._manifest_root(run_id)
        blockers: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        target_partitions: list[dict[str, Any]] = []
        gate_plan: list[dict[str, Any]] = []

        if not manifest_root.exists():
            raise FileNotFoundError(f"未找到 DuckDB compute run manifest：{_relpath(manifest_root, self.lake_root)}")

        run_payload = _read_json(manifest_root / "run.json")
        self._validate_run_payload(run_payload=run_payload, blockers=blockers, allowed_run_statuses=allowed_run_statuses or {"prewrite_backup"})
        self._validate_prewrite_backup(manifest_root=manifest_root, run_payload=run_payload, blockers=blockers)
        self._validate_audit_ledger(manifest_root=manifest_root, blockers=blockers)

        publish_rows = self._read_publish_rows(
            manifest_root=manifest_root,
            blockers=blockers,
            allowed_publish_statuses=allowed_publish_statuses or {"audit_passed"},
        )
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

    def stage_stk_mins_qfq_gate_publishing(
        self,
        *,
        run_id: str,
        progress_callback: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        """Write the formal clean_next gate rows to publishing.

        M3-C-C opens the formal publish window. It intentionally stops before
        replacing formal partitions, writing downstream requirements, or marking
        the gate passed.
        """

        manifest_root = self._manifest_root(run_id)
        if not manifest_root.exists():
            raise FileNotFoundError(f"未找到 DuckDB compute run manifest：{_relpath(manifest_root, self.lake_root)}")

        store = LakeJobStateStore(self.lake_root)
        lock_service = LakeJobLockService(store, stale_after_seconds=self.settings.compute_stale_heartbeat_seconds)
        lock_acquired: dict[str, Any] | None = None
        try:
            lock_acquired = lock_service.acquire(run_id=run_id, profile_key="duckdb_compute_stk_mins_qfq")
            _emit_progress(progress_callback, {"event": "formal_gate_publishing_started", "run_id": run_id})
            plan_payload = self._read_gate_publish_plan(manifest_root=manifest_root, run_id=run_id)
            preflight = self.preflight_stk_mins_qfq_publish(
                run_id=run_id,
                progress_callback=progress_callback,
                allow_lock_run_id=run_id,
                allowed_publish_statuses={"audit_passed", "publishing"},
            )
            if not preflight["ready"]:
                return {
                    "operation": "stage_stk_mins_qfq_gate_publishing",
                    "stage": "m3c_c_formal_gate_publishing",
                    "run_id": run_id,
                    "status": "blocked",
                    "ready": False,
                    "write_intent": False,
                    "formal_paths_touched": [],
                    "preflight": preflight,
                    "message": "M3-C-C 未写 formal gate；preflight 仍存在阻断项。",
                    "lock_acquired": lock_acquired,
                    "lock_after": None,
                }

            blockers = self._validate_gate_publish_plan(plan_payload=plan_payload, preflight=preflight)
            if blockers:
                return {
                    "operation": "stage_stk_mins_qfq_gate_publishing",
                    "stage": "m3c_c_formal_gate_publishing",
                    "run_id": run_id,
                    "status": "blocked",
                    "ready": False,
                    "write_intent": False,
                    "formal_paths_touched": [],
                    "blockers": blockers,
                    "message": "M3-C-C 未写 formal gate；gate publishing 计划与当前 preflight 不一致。",
                    "lock_acquired": lock_acquired,
                    "lock_after": None,
                }

            gate_statuses = [_gate_status_from_plan_row(row) for row in plan_payload["gate_rows"]]
            gate_write = CleanNextPartitionGateService(lake_root=self.lake_root).write_statuses(gate_statuses, run_id=run_id)
            publish_update = self._write_publish_partitions_status(manifest_root=manifest_root, status="publishing")
            run_payload = _read_json(manifest_root / "run.json")
            run_payload = {
                **run_payload,
                "status": "publishing",
                "m3c_c_gate_publishing": {
                    "status": "success",
                    "finished_at": _utc_now_iso(),
                    "formal_gate_file": _relpath(self.lake_root / CLEAN_NEXT_GATE_RELATIVE_PATH, self.lake_root),
                    "updated_gate_partitions": gate_write["updated_partitions"],
                    "updated_publish_partitions": publish_update["updated_partitions"],
                    "formal_paths_touched": [_relpath(self.lake_root / CLEAN_NEXT_GATE_RELATIVE_PATH, self.lake_root)],
                },
                "finished_at": None,
                "error": None,
            }
            _write_json_atomic(manifest_root / "run.json", run_payload)
            _append_publish_event(
                manifest_root / "events.jsonl",
                {
                    "event_type": "formal_gate_publishing_staged",
                    "level": "info",
                    "message": "M3-C-C 已把目标 formal gate 写为 publishing；尚未替换正式分区，尚未写 downstream requirement，尚未 gate passed。",
                    "metrics": {
                        "updated_gate_partitions": gate_write["updated_partitions"],
                        "updated_publish_partitions": publish_update["updated_partitions"],
                    },
                },
            )
            lock_service.heartbeat(run_id=run_id)
            _emit_progress(
                progress_callback,
                {
                    "event": "formal_gate_publishing_completed",
                    "run_id": run_id,
                    "updated_gate_partitions": gate_write["updated_partitions"],
                },
            )
            return {
                "operation": "stage_stk_mins_qfq_gate_publishing",
                "stage": "m3c_c_formal_gate_publishing",
                "run_id": run_id,
                "status": "formal_gate_publishing_staged",
                "ready": True,
                "write_intent": True,
                "formal_paths_touched": [_relpath(self.lake_root / CLEAN_NEXT_GATE_RELATIVE_PATH, self.lake_root)],
                "manifest_root": _relpath(manifest_root, self.lake_root),
                "gate_write": gate_write,
                "publish_update": publish_update,
                "message": "M3-C-C formal gate 已写为 publishing；正式数据尚未替换，下游仍被 gate 阻断。",
                "lock_acquired": lock_acquired,
                "lock_after": None,
            }
        finally:
            if lock_acquired is not None:
                lock_service.release(run_id=run_id)

    def stage_stk_mins_qfq_formal_replace_and_audit(
        self,
        *,
        run_id: str,
        progress_callback: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        """Replace formal clean_next partitions and write formal audit evidence.

        M3-C-D still stops before downstream requirement/queue writes and before
        gate=passed. It requires M3-C-C to have already written formal gates to
        publishing for the same run revision.
        """

        manifest_root = self._manifest_root(run_id)
        if not manifest_root.exists():
            raise FileNotFoundError(f"未找到 DuckDB compute run manifest：{_relpath(manifest_root, self.lake_root)}")

        store = LakeJobStateStore(self.lake_root)
        lock_service = LakeJobLockService(store, stale_after_seconds=self.settings.compute_stale_heartbeat_seconds)
        lock_acquired: dict[str, Any] | None = None
        try:
            lock_acquired = lock_service.acquire(run_id=run_id, profile_key="duckdb_compute_stk_mins_qfq")
            _emit_progress(progress_callback, {"event": "formal_replace_started", "run_id": run_id})

            run_payload = _read_json(manifest_root / "run.json")
            idempotent = self._maybe_return_m3c_d_idempotent(manifest_root=manifest_root, run_payload=run_payload, lock_acquired=lock_acquired)
            if idempotent is not None:
                return idempotent

            plan_payload = self._read_gate_publish_plan(manifest_root=manifest_root, run_id=run_id)
            readiness_blockers = self._validate_m3c_d_readiness(run_payload=run_payload)
            if readiness_blockers:
                return {
                    "operation": "stage_stk_mins_qfq_formal_replace_and_audit",
                    "stage": "m3c_d_formal_replace_and_audit",
                    "run_id": run_id,
                    "status": "blocked",
                    "ready": False,
                    "write_intent": False,
                    "formal_paths_touched": [],
                    "blockers": readiness_blockers,
                    "message": "M3-C-D 未替换正式分区；run 尚未完成 M3-C-C gate publishing。",
                    "lock_acquired": lock_acquired,
                    "lock_after": None,
                }

            preflight = self.preflight_stk_mins_qfq_publish(
                run_id=run_id,
                progress_callback=progress_callback,
                allow_lock_run_id=run_id,
                allowed_publish_statuses={"publishing"},
                allowed_run_statuses={"publishing"},
            )
            if not preflight["ready"]:
                return {
                    "operation": "stage_stk_mins_qfq_formal_replace_and_audit",
                    "stage": "m3c_d_formal_replace_and_audit",
                    "run_id": run_id,
                    "status": "blocked",
                    "ready": False,
                    "write_intent": False,
                    "formal_paths_touched": [],
                    "preflight": preflight,
                    "message": "M3-C-D 未替换正式分区；preflight 仍存在阻断项。",
                    "lock_acquired": lock_acquired,
                    "lock_after": None,
                }

            blockers = self._validate_gate_publish_plan(plan_payload=plan_payload, preflight=preflight)
            blockers.extend(self._validate_formal_gate_is_publishing(plan_payload=plan_payload))
            if blockers:
                return {
                    "operation": "stage_stk_mins_qfq_formal_replace_and_audit",
                    "stage": "m3c_d_formal_replace_and_audit",
                    "run_id": run_id,
                    "status": "blocked",
                    "ready": False,
                    "write_intent": False,
                    "formal_paths_touched": [],
                    "blockers": blockers,
                    "message": "M3-C-D 未替换正式分区；formal gate 或 gate plan 未满足发布条件。",
                    "lock_acquired": lock_acquired,
                    "lock_after": None,
                }

            run_payload = {
                **run_payload,
                "status": "publishing",
                "m3c_d_formal_publish": {
                    "status": "running",
                    "started_at": _utc_now_iso(),
                    "message": "M3-C-D 正在原子替换正式 clean_next 分区并执行 formal audit。",
                },
                "finished_at": None,
                "error": None,
            }
            _write_json_atomic(manifest_root / "run.json", run_payload)

            replaced_partitions: list[dict[str, Any]] = []
            issues: list[dict[str, Any]] = []
            for index, partition in enumerate(preflight["target_partitions"], start=1):
                _emit_progress(
                    progress_callback,
                    {
                        "event": "formal_partition_replace_started",
                        "run_id": run_id,
                        "partition_index": index,
                        "partition_count": len(preflight["target_partitions"]),
                        "partition_key": partition["partition_key"],
                    },
                )
                replaced = self._replace_formal_partition_from_candidate(run_id=run_id, partition=partition)
                replaced_partitions.append(replaced)
                issues.extend(self._audit_formal_partition(run_id=run_id, partition=partition))
                lock_service.heartbeat(run_id=run_id)
                _emit_progress(
                    progress_callback,
                    {
                        "event": "formal_partition_replace_finished",
                        "run_id": run_id,
                        "partition_index": index,
                        "partition_count": len(preflight["target_partitions"]),
                        "partition_key": partition["partition_key"],
                        "target_path": replaced["target_path"],
                    },
                )

            ledger_path = manifest_root / FORMAL_AUDIT_LEDGER_FILENAME
            _write_formal_audit_ledger(ledger_path, issues)
            if issues:
                self._write_publish_partitions_status(manifest_root=manifest_root, status="formal_audit_failed")
                blocked_payload = {
                    **_read_json(manifest_root / "run.json"),
                    "status": "blocked",
                    "m3c_d_formal_publish": {
                        "status": "failed",
                        "finished_at": _utc_now_iso(),
                        "formal_audit_ledger": _relpath(ledger_path, self.lake_root),
                        "issue_count": len(issues),
                        "formal_paths_touched": [item["target_path"] for item in replaced_partitions],
                    },
                    "error": {
                        "error_code": "LC_COMPUTE_FORMAL_AUDIT_FAILED",
                        "stage": "formal_publish_audit",
                        "message_for_human": "正式分区替换后 formal audit 未通过；gate 未放行，下游仍被阻断。",
                        "technical_detail": f"issue_count={len(issues)}",
                    },
                }
                _write_json_atomic(manifest_root / "run.json", blocked_payload)
                _append_publish_event(
                    manifest_root / "events.jsonl",
                    {
                        "event_type": "formal_partition_audit_failed",
                        "level": "error",
                        "message": "M3-C-D formal audit 未通过；未写 downstream，未 gate passed。",
                        "metrics": {"issue_count": len(issues), "replaced_partition_count": len(replaced_partitions)},
                    },
                )
                return {
                    "operation": "stage_stk_mins_qfq_formal_replace_and_audit",
                    "stage": "m3c_d_formal_replace_and_audit",
                    "run_id": run_id,
                    "status": "blocked",
                    "ready": False,
                    "write_intent": True,
                    "formal_paths_touched": [item["target_path"] for item in replaced_partitions],
                    "formal_audit_ledger": _relpath(ledger_path, self.lake_root),
                    "issue_count": len(issues),
                    "message": "M3-C-D 已替换正式分区，但 formal audit 未通过；下游仍被 publishing gate 阻断。",
                    "lock_acquired": lock_acquired,
                    "lock_after": None,
                }

            publish_update = self._write_publish_partitions_status(manifest_root=manifest_root, status="published")
            final_payload = {
                **_read_json(manifest_root / "run.json"),
                "status": "publishing",
                "m3c_d_formal_publish": {
                    "status": "success",
                    "finished_at": _utc_now_iso(),
                    "formal_audit_ledger": _relpath(ledger_path, self.lake_root),
                    "issue_count": 0,
                    "replaced_partition_count": len(replaced_partitions),
                    "updated_publish_partitions": publish_update["updated_partitions"],
                    "formal_paths_touched": [item["target_path"] for item in replaced_partitions],
                },
                "finished_at": None,
                "error": None,
            }
            _write_json_atomic(manifest_root / "run.json", final_payload)
            _append_publish_event(
                manifest_root / "events.jsonl",
                {
                    "event_type": "formal_partitions_replaced_and_audited",
                    "level": "info",
                    "message": "M3-C-D 已原子替换正式 clean_next 分区并通过 formal audit；尚未写 downstream，尚未 gate passed。",
                    "metrics": {
                        "replaced_partition_count": len(replaced_partitions),
                        "formal_audit_issue_count": 0,
                    },
                },
            )
            lock_service.heartbeat(run_id=run_id)
            return {
                "operation": "stage_stk_mins_qfq_formal_replace_and_audit",
                "stage": "m3c_d_formal_replace_and_audit",
                "run_id": run_id,
                "status": "formal_partitions_published",
                "ready": True,
                "write_intent": True,
                "formal_paths_touched": [item["target_path"] for item in replaced_partitions],
                "formal_audit_ledger": _relpath(ledger_path, self.lake_root),
                "publish_update": publish_update,
                "metrics": {
                    "replaced_partition_count": len(replaced_partitions),
                    "formal_audit_issue_count": 0,
                    "formal_row_count": sum(int(item["row_count"]) for item in replaced_partitions),
                },
                "message": "M3-C-D formal replace + audit 已完成；下游仍被 publishing gate 阻断，等待 M3-C-E。",
                "lock_acquired": lock_acquired,
                "lock_after": None,
            }
        finally:
            if lock_acquired is not None:
                lock_service.release(run_id=run_id)

    def stage_stk_mins_qfq_downstream_and_gate_passed(
        self,
        *,
        run_id: str,
        progress_callback: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        """Write downstream notifications, then mark formal gate passed.

        M3-C-E is the first stage that releases downstream consumers. The order
        is fixed: downstream requirement, indicator source event/queue, and only
        then clean_next gate=passed.
        """

        manifest_root = self._manifest_root(run_id)
        if not manifest_root.exists():
            raise FileNotFoundError(f"未找到 DuckDB compute run manifest：{_relpath(manifest_root, self.lake_root)}")

        store = LakeJobStateStore(self.lake_root)
        lock_service = LakeJobLockService(store, stale_after_seconds=self.settings.compute_stale_heartbeat_seconds)
        lock_acquired: dict[str, Any] | None = None
        try:
            lock_acquired = lock_service.acquire(run_id=run_id, profile_key="duckdb_compute_stk_mins_qfq")
            _emit_progress(progress_callback, {"event": "downstream_notification_started", "run_id": run_id})

            run_payload = _read_json(manifest_root / "run.json")
            idempotent = self._maybe_return_m3c_e_idempotent(run_payload=run_payload, lock_acquired=lock_acquired)
            if idempotent is not None:
                return idempotent

            plan_payload = self._read_gate_publish_plan(manifest_root=manifest_root, run_id=run_id)
            preflight = self.preflight_stk_mins_qfq_publish(
                run_id=run_id,
                progress_callback=progress_callback,
                allow_lock_run_id=run_id,
                allowed_publish_statuses={"published"},
                allowed_run_statuses={"publishing"},
            )
            blockers = []
            if not preflight["ready"]:
                blockers.extend(preflight["blockers"])
            blockers.extend(self._validate_m3c_e_readiness(run_payload=run_payload, manifest_root=manifest_root))
            blockers.extend(self._validate_formal_gate_is_publishing(plan_payload=plan_payload))
            if blockers:
                return {
                    "operation": "stage_stk_mins_qfq_downstream_and_gate_passed",
                    "stage": "m3c_e_downstream_and_gate_passed",
                    "run_id": run_id,
                    "status": "blocked",
                    "ready": False,
                    "write_intent": False,
                    "formal_paths_touched": [],
                    "blockers": blockers,
                    "message": "M3-C-E 未写 downstream/queue，未 gate passed；前置条件不满足。",
                    "lock_acquired": lock_acquired,
                    "lock_after": None,
                }

            try:
                downstream_requirements = DownstreamRebuildRequirementService(lake_root=self.lake_root).build_stk_mins_qfq_requirements(
                    source_publish_id=run_id,
                    publish_partitions=preflight["target_partitions"],
                )
                downstream_write = DownstreamRebuildRequirementService(lake_root=self.lake_root).upsert_requirements(
                    requirements=downstream_requirements,
                    run_id=run_id,
                )
                indicator_events = self._record_indicator_recalc_events(run_id=run_id, partitions=preflight["target_partitions"])
            except Exception as exc:
                failed_payload = {
                    **run_payload,
                    "status": "publishing",
                    "m3c_e_downstream_and_gate_passed": {
                        "status": "failed",
                        "finished_at": _utc_now_iso(),
                        "gate_passed": False,
                    },
                    "error": {
                        "error_code": "LC_COMPUTE_DOWNSTREAM_NOTIFICATION_FAILED",
                        "stage": "downstream_notification",
                        "message_for_human": "下游重建通知或指标重算队列写入失败；clean_next gate 保持 publishing，下游仍被阻断。",
                        "technical_detail": str(exc),
                    },
                }
                _write_json_atomic(manifest_root / "run.json", failed_payload)
                _append_publish_event(
                    manifest_root / "events.jsonl",
                    {
                        "event_type": "downstream_notification_failed",
                        "level": "error",
                        "message": "M3-C-E 下游通知失败；未 gate passed。",
                        "error": str(exc),
                    },
                )
                raise

            gate_statuses = [_gate_passed_status_from_plan_row(row) for row in plan_payload["gate_rows"]]
            try:
                gate_write = CleanNextPartitionGateService(lake_root=self.lake_root).write_statuses(gate_statuses, run_id=run_id)
            except Exception as exc:
                gate_failed_payload = {
                    **_read_json(manifest_root / "run.json"),
                    "status": "publishing",
                    "m3c_e_downstream_and_gate_passed": {
                        "status": "failed",
                        "finished_at": _utc_now_iso(),
                        "gate_passed": False,
                    },
                    "error": {
                        "error_code": "LC_COMPUTE_FINAL_GATE_FAILED",
                        "stage": "final_gate_passed",
                        "message_for_human": "下游通知已写入，但 final gate passed 写入失败；clean_next gate 仍应保持 publishing，下游仍被阻断。",
                        "technical_detail": str(exc),
                    },
                }
                _write_json_atomic(manifest_root / "run.json", gate_failed_payload)
                _append_publish_event(
                    manifest_root / "events.jsonl",
                    {
                        "event_type": "final_gate_passed_failed",
                        "level": "error",
                        "message": "M3-C-E final gate passed 写入失败；下游通知已写入但 gate 未放行。",
                        "error": str(exc),
                    },
                )
                raise
            final_payload = {
                **_read_json(manifest_root / "run.json"),
                "status": "published",
                "m3c_e_downstream_and_gate_passed": {
                    "status": "success",
                    "finished_at": _utc_now_iso(),
                    "downstream_requirement_file": _relpath(self.lake_root / DOWNSTREAM_REBUILD_REQUIREMENT_RELATIVE_PATH, self.lake_root),
                    "downstream_requirement_count": len(downstream_requirements),
                    "indicator_event_count": len(indicator_events),
                    "indicator_event_written_count": len([item for item in indicator_events if item.get("event_written")]),
                    "updated_gate_partitions": gate_write["updated_partitions"],
                    "gate_passed": True,
                },
                "finished_at": _utc_now_iso(),
                "error": None,
            }
            _write_json_atomic(manifest_root / "run.json", final_payload)
            _append_publish_event(
                manifest_root / "events.jsonl",
                {
                    "event_type": "downstream_notified_and_gate_passed",
                    "level": "info",
                    "message": "M3-C-E 已写 downstream requirement 和 indicator queue，随后把 clean_next gate 标记为 passed。",
                    "metrics": {
                        "downstream_requirement_count": len(downstream_requirements),
                        "indicator_event_count": len(indicator_events),
                        "updated_gate_partitions": gate_write["updated_partitions"],
                    },
                },
            )
            lock_service.heartbeat(run_id=run_id)
            return {
                "operation": "stage_stk_mins_qfq_downstream_and_gate_passed",
                "stage": "m3c_e_downstream_and_gate_passed",
                "run_id": run_id,
                "status": "published",
                "ready": True,
                "write_intent": True,
                "formal_paths_touched": [
                    _relpath(self.lake_root / DOWNSTREAM_REBUILD_REQUIREMENT_RELATIVE_PATH, self.lake_root),
                    "manifest/source_partition_events/stk_mins.jsonl",
                    "manifest/indicator_recalc_queue/stk_mins_macd.parquet",
                    _relpath(self.lake_root / CLEAN_NEXT_GATE_RELATIVE_PATH, self.lake_root),
                ],
                "downstream_write": downstream_write,
                "indicator_events": indicator_events,
                "gate_write": gate_write,
                "message": "M3-C-E 下游通知和 final gate passed 已完成；publisher 全链路可以进入 tmp 小样本验证。",
                "lock_acquired": lock_acquired,
                "lock_after": None,
            }
        finally:
            if lock_acquired is not None:
                lock_service.release(run_id=run_id)

    def _validate_run_payload(
        self,
        *,
        run_payload: dict[str, Any],
        blockers: list[dict[str, Any]],
        allowed_run_statuses: set[str],
    ) -> None:
        if run_payload.get("job_type") != "stk_mins_qfq_clean_next":
            blockers.append(
                {
                    "code": "unsupported_job_type",
                    "message": "当前 run 不是 stk_mins qfq clean_next 发布任务。",
                    "actual": run_payload.get("job_type"),
                }
            )
        if str(run_payload.get("status") or "") not in allowed_run_statuses:
            blockers.append(
                {
                    "code": "run_status_not_allowed_for_publish_stage",
                    "message": "当前 run 状态不在本发布阶段允许范围内。",
                    "actual": run_payload.get("status"),
                    "allowed": sorted(allowed_run_statuses),
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

    def _read_publish_rows(
        self,
        *,
        manifest_root: Path,
        blockers: list[dict[str, Any]],
        allowed_publish_statuses: set[str],
    ) -> list[dict[str, Any]]:
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
            if str(row.get("audit_status") or "") != "passed" or str(row.get("publish_status") or "") not in allowed_publish_statuses
        ]
        if bad_rows:
            blockers.append(
                {
                    "code": "publish_partitions_not_audit_passed",
                    "message": "仍有发布分区未通过 candidate audit，或发布状态不在当前阶段允许范围内。",
                    "actual": [row.get("partition_key") for row in bad_rows[:10]],
                    "allowed_publish_statuses": sorted(allowed_publish_statuses),
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
            "source_candidate_parts_json": row.get("source_candidate_parts_json"),
            "expected_candidate_part_paths_json": row.get("expected_candidate_part_paths_json"),
            "expected_candidate_part_count": row.get("expected_candidate_part_count"),
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

    def _read_gate_publish_plan(self, *, manifest_root: Path, run_id: str) -> dict[str, Any]:
        plan_file = manifest_root / GATE_PUBLISH_PLAN_FILENAME
        if not plan_file.exists():
            raise FileNotFoundError(f"缺少 M3-C-B gate publishing 计划：{_relpath(plan_file, self.lake_root)}")
        plan_payload = _read_json(plan_file)
        if plan_payload.get("stage") != "m3c_b_gate_publish_plan":
            raise RuntimeError(f"gate publishing 计划 stage 非法：{plan_payload.get('stage')}")
        if str(plan_payload.get("run_id") or "") != run_id:
            raise RuntimeError(f"gate publishing 计划 run_id 不匹配：{plan_payload.get('run_id')} != {run_id}")
        gate_rows = plan_payload.get("gate_rows")
        if not isinstance(gate_rows, list) or not gate_rows:
            raise RuntimeError("gate publishing 计划缺少 gate_rows。")
        return plan_payload

    def _validate_gate_publish_plan(self, *, plan_payload: dict[str, Any], preflight: dict[str, Any]) -> list[dict[str, Any]]:
        blockers: list[dict[str, Any]] = []
        plan_by_key = {str(row.get("partition_key") or ""): row for row in plan_payload["gate_rows"]}
        preflight_keys = {str(row.get("partition_key") or "") for row in preflight["target_partitions"]}
        if set(plan_by_key) != preflight_keys:
            blockers.append(
                {
                    "code": "gate_publish_plan_partition_mismatch",
                    "message": "M3-C-B gate publishing 计划中的分区集合与当前 preflight 不一致。",
                    "planned_only": sorted(set(plan_by_key) - preflight_keys)[:10],
                    "preflight_only": sorted(preflight_keys - set(plan_by_key))[:10],
                }
            )
        current_gate_by_key = {
            str(row.get("partition_key") or ""): row
            for row in CleanNextPartitionGateService(lake_root=self.lake_root).read_statuses()
        }
        for partition_key, planned in plan_by_key.items():
            current = current_gate_by_key.get(partition_key)
            if not current:
                continue
            if str(current.get("status") or "") == "publishing" and str(current.get("write_revision") or "") != str(planned.get("write_revision") or ""):
                blockers.append(
                    {
                        "code": "formal_gate_already_publishing_by_other_revision",
                        "message": "目标 formal gate 已被其它发布写成 publishing，不能覆盖。",
                        "partition_key": partition_key,
                        "current_write_revision": current.get("write_revision"),
                        "planned_write_revision": planned.get("write_revision"),
                    }
                )
        return blockers

    def _write_publish_partitions_status(self, *, manifest_root: Path, status: str) -> dict[str, Any]:
        publish_file = manifest_root / "publish_partitions.parquet"
        rows = _read_manifest_rows(publish_file)
        updated_rows = [{**row, "publish_status": status} for row in rows]
        _write_parquet_manifest(publish_file, updated_rows, columns=PUBLISH_PARTITION_COLUMNS)
        return {
            "path": _relpath(publish_file, self.lake_root),
            "updated_partitions": len(updated_rows),
            "publish_status": status,
        }

    def _maybe_return_m3c_d_idempotent(
        self,
        *,
        manifest_root: Path,
        run_payload: dict[str, Any],
        lock_acquired: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        state = run_payload.get("m3c_d_formal_publish") or {}
        if state.get("status") != "success":
            return None
        publish_rows = _read_manifest_rows(manifest_root / "publish_partitions.parquet")
        if any(str(row.get("publish_status") or "") != "published" for row in publish_rows):
            return None
        return {
            "operation": "stage_stk_mins_qfq_formal_replace_and_audit",
            "stage": "m3c_d_formal_replace_and_audit",
            "run_id": run_payload.get("run_id"),
            "status": "formal_partitions_published",
            "ready": True,
            "idempotent": True,
            "write_intent": False,
            "formal_paths_touched": [],
            "formal_audit_ledger": state.get("formal_audit_ledger"),
            "metrics": {
                "replaced_partition_count": int(state.get("replaced_partition_count") or 0),
                "formal_audit_issue_count": int(state.get("issue_count") or 0),
            },
            "message": "M3-C-D 已完成，本次未重复替换正式分区。",
            "lock_acquired": lock_acquired,
            "lock_after": None,
        }

    def _validate_m3c_d_readiness(self, *, run_payload: dict[str, Any]) -> list[dict[str, Any]]:
        blockers: list[dict[str, Any]] = []
        if run_payload.get("status") != "publishing":
            blockers.append(
                {
                    "code": "run_not_formal_gate_publishing",
                    "message": "M3-C-D 必须在 M3-C-C 已打开 publishing gate 后执行。",
                    "actual": run_payload.get("status"),
                }
            )
        gate_state = run_payload.get("m3c_c_gate_publishing") or {}
        if gate_state.get("status") != "success":
            blockers.append(
                {
                    "code": "m3c_c_gate_publishing_missing",
                    "message": "run.json 中缺少成功的 M3-C-C formal gate publishing 状态。",
                    "actual": gate_state,
                }
            )
        return blockers

    def _maybe_return_m3c_e_idempotent(
        self,
        *,
        run_payload: dict[str, Any],
        lock_acquired: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        state = run_payload.get("m3c_e_downstream_and_gate_passed") or {}
        if state.get("status") != "success" or run_payload.get("status") != "published":
            return None
        return {
            "operation": "stage_stk_mins_qfq_downstream_and_gate_passed",
            "stage": "m3c_e_downstream_and_gate_passed",
            "run_id": run_payload.get("run_id"),
            "status": "published",
            "ready": True,
            "idempotent": True,
            "write_intent": False,
            "formal_paths_touched": [],
            "metrics": {
                "downstream_requirement_count": int(state.get("downstream_requirement_count") or 0),
                "indicator_event_count": int(state.get("indicator_event_count") or 0),
                "updated_gate_partitions": int(state.get("updated_gate_partitions") or 0),
            },
            "message": "M3-C-E 已完成，本次未重复写 downstream、queue 或 gate。",
            "lock_acquired": lock_acquired,
            "lock_after": None,
        }

    def _validate_m3c_e_readiness(self, *, run_payload: dict[str, Any], manifest_root: Path) -> list[dict[str, Any]]:
        blockers: list[dict[str, Any]] = []
        formal_state = run_payload.get("m3c_d_formal_publish") or {}
        if run_payload.get("status") != "publishing":
            blockers.append(
                {
                    "code": "run_not_waiting_for_downstream_publish",
                    "message": "M3-C-E 必须在 M3-C-D 成功后、run 仍停在 publishing 时执行。",
                    "actual": run_payload.get("status"),
                }
            )
        if formal_state.get("status") != "success":
            blockers.append(
                {
                    "code": "m3c_d_formal_publish_missing",
                    "message": "run.json 中缺少成功的 M3-C-D formal publish 状态。",
                    "actual": formal_state,
                }
            )
        ledger_path = manifest_root / FORMAL_AUDIT_LEDGER_FILENAME
        if not ledger_path.exists():
            blockers.append(
                {
                    "code": "formal_audit_ledger_missing",
                    "message": "缺少 formal_audit_ledger.parquet，不能 final gate passed。",
                    "path": _relpath(ledger_path, self.lake_root),
                }
            )
        else:
            issue_rows = _read_manifest_rows(ledger_path)
            if issue_rows:
                blockers.append(
                    {
                        "code": "formal_audit_has_open_issues",
                        "message": "formal audit ledger 仍有问题，不能 final gate passed。",
                        "actual": {"issue_count": len(issue_rows)},
                    }
                )
        return blockers

    def _validate_formal_gate_is_publishing(self, *, plan_payload: dict[str, Any]) -> list[dict[str, Any]]:
        blockers: list[dict[str, Any]] = []
        current_gate_by_key = {
            str(row.get("partition_key") or ""): row
            for row in CleanNextPartitionGateService(lake_root=self.lake_root).read_statuses()
        }
        for planned in plan_payload["gate_rows"]:
            partition_key = str(planned.get("partition_key") or "")
            current = current_gate_by_key.get(partition_key)
            if current is None:
                blockers.append(
                    {
                        "code": "formal_gate_publishing_missing",
                        "message": "目标分区缺少 M3-C-C 写入的 publishing gate，不能替换正式分区。",
                        "partition_key": partition_key,
                    }
                )
                continue
            if str(current.get("status") or "") != "publishing":
                blockers.append(
                    {
                        "code": "formal_gate_not_publishing",
                        "message": "目标分区 formal gate 不是 publishing，不能替换正式分区。",
                        "partition_key": partition_key,
                        "actual": current.get("status"),
                    }
                )
            if str(current.get("write_revision") or "") != str(planned.get("write_revision") or ""):
                blockers.append(
                    {
                        "code": "formal_gate_write_revision_mismatch",
                        "message": "目标分区 formal gate write_revision 与当前 run 计划不一致。",
                        "partition_key": partition_key,
                        "expected": planned.get("write_revision"),
                        "actual": current.get("write_revision"),
                    }
                )
        return blockers

    def _record_indicator_recalc_events(self, *, run_id: str, partitions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        service = IndicatorRecalcQueueService(lake_root=self.lake_root)
        results: list[dict[str, Any]] = []
        for partition in partitions:
            parsed = _parse_partition_key(str(partition["partition_key"]))
            metadata = _partition_metadata(_resolve_lake_path(self.lake_root, str(partition["target_path"])))
            result = service.record_source_partition_replaced(
                layer="research/stk_mins_by_date_clean_next",
                freq=int(parsed["freq"]),
                trade_date=parsed["trade_date"],
                run_id=run_id,
                written_rows=int(metadata["row_count"]),
            )
            results.append(
                {
                    "partition_key": partition["partition_key"],
                    "event_id": result["event"]["event_id"],
                    "event_written": bool(result.get("event_written")),
                    "queue_id": result["queue_item"]["queue_id"],
                    "queue_status": result["queue_item"]["status"],
                }
            )
        return results

    def _replace_formal_partition_from_candidate(self, *, run_id: str, partition: dict[str, Any]) -> dict[str, Any]:
        partition_key = str(partition["partition_key"])
        target_path = str(partition["target_path"])
        target_absolute = _resolve_lake_path(self.lake_root, target_path)
        candidate_paths = [
            _resolve_candidate_path(self.lake_root, run_id, str(raw_path))
            for raw_path in _json_array(partition.get("source_candidate_parts_json"))
        ]
        tmp_dir = self.lake_root / "_tmp" / "duckdb_compute" / run_id / "formal_replace" / partition_key
        if tmp_dir.exists():
            raise RuntimeError(f"M3-C-D tmp formal replace 目录已存在，拒绝覆盖：{_relpath(tmp_dir, self.lake_root)}")
        tmp_dir.mkdir(parents=True, exist_ok=False)
        for index, candidate_path in enumerate(candidate_paths):
            shutil.copy2(candidate_path, tmp_dir / f"part-{index:05d}.parquet")
        backup_root = self.lake_root / "_tmp" / "duckdb_compute" / run_id / "formal_replace_backup" / partition_key
        replace_directory_atomically(tmp_dir=tmp_dir, final_dir=target_absolute, backup_root=backup_root)
        metadata = _partition_metadata(target_absolute)
        return {
            "partition_key": partition_key,
            "target_path": target_path,
            "candidate_part_count": len(candidate_paths),
            "file_count": metadata["file_count"],
            "row_count": metadata["row_count"],
            "byte_count": metadata["byte_count"],
        }

    def _audit_formal_partition(self, *, run_id: str, partition: dict[str, Any]) -> list[dict[str, Any]]:
        partition_key = str(partition["partition_key"])
        target_path = str(partition["target_path"])
        target_absolute = _resolve_lake_path(self.lake_root, target_path)
        issues: list[dict[str, Any]] = []
        if not target_absolute.exists():
            return [
                _formal_issue(
                    run_id=run_id,
                    partition_key=partition_key,
                    code="formal_partition_missing_after_replace",
                    message="atomic replace 后正式分区目录不存在。",
                    target_path=target_path,
                )
            ]
        metadata = _partition_metadata(target_absolute)
        if metadata["file_count"] == 0:
            issues.append(
                _formal_issue(
                    run_id=run_id,
                    partition_key=partition_key,
                    code="formal_partition_has_no_parquet_files",
                    message="atomic replace 后正式分区没有 parquet 文件。",
                    target_path=target_path,
                )
            )
        expected_row_count = int(partition.get("candidate_row_count") or 0)
        if int(metadata["row_count"]) != expected_row_count:
            issues.append(
                _formal_issue(
                    run_id=run_id,
                    partition_key=partition_key,
                    code="formal_partition_row_count_mismatch",
                    message="正式分区行数与 candidate 行数不一致。",
                    target_path=target_path,
                    expected=expected_row_count,
                    actual=int(metadata["row_count"]),
                )
            )
        expected_columns = tuple(EXPECTED_QFQ_CANDIDATE_COLUMNS)
        for file_path, columns in metadata["columns_by_file"].items():
            if tuple(columns) != expected_columns:
                issues.append(
                    _formal_issue(
                        run_id=run_id,
                        partition_key=partition_key,
                        code="formal_partition_schema_mismatch",
                        message="正式分区 schema 与 qfq clean_next 口径不一致。",
                        target_path=_relpath(file_path, self.lake_root),
                        expected=list(expected_columns),
                        actual=list(columns),
                    )
                )
        return issues


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
    return {
        "row_count": int(parquet_file.metadata.num_rows),
        "columns": tuple(parquet_file.schema.names),
    }


def _partition_metadata(partition_dir: Path) -> dict[str, Any]:
    files = sorted(path for path in partition_dir.glob("*.parquet") if path.is_file())
    row_count = 0
    byte_count = 0
    columns_by_file: dict[Path, tuple[str, ...]] = {}
    for file_path in files:
        metadata = _parquet_metadata(file_path)
        row_count += int(metadata["row_count"])
        byte_count += int(file_path.stat().st_size)
        columns_by_file[file_path] = tuple(metadata["columns"])
    return {
        "file_count": len(files),
        "row_count": row_count,
        "byte_count": byte_count,
        "columns_by_file": columns_by_file,
    }


def _formal_issue(
    *,
    run_id: str,
    partition_key: str,
    code: str,
    message: str,
    target_path: str,
    expected: Any = None,
    actual: Any = None,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "partition_key": partition_key,
        "issue_code": code,
        "severity": "block",
        "target_path": target_path,
        "message": message,
        "expected_value": _json_text(expected) if expected is not None else None,
        "actual_value": _json_text(actual) if actual is not None else None,
        "observed_at": _utc_now_iso(),
    }


def _write_formal_audit_ledger(path: Path, issues: list[dict[str, Any]]) -> None:
    _write_parquet_manifest(
        path,
        [{column: row.get(column) for column in FORMAL_AUDIT_LEDGER_COLUMNS} for row in issues],
        columns=FORMAL_AUDIT_LEDGER_COLUMNS,
    )


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


def _gate_status_from_plan_row(row: dict[str, Any]) -> CleanNextGateStatus:
    return CleanNextGateStatus(
        freq=int(row["freq"]),
        trade_date=date.fromisoformat(str(row["trade_date"])),
        clean_partition_path=str(row["clean_partition_path"]),
        source_run_id=str(row["source_run_id"]),
        clean_run_id=str(row["clean_run_id"]),
        write_revision=str(row["write_revision"]),
        status="publishing",
        issue_count=int(row.get("issue_count") or 0),
        raw_rows=int(row.get("raw_rows") or 0),
        clean_rows=int(row.get("clean_rows") or 0),
        ledger_path=str(row.get("ledger_path") or ""),
        message=str(row.get("message") or "publishing"),
    )


def _gate_passed_status_from_plan_row(row: dict[str, Any]) -> CleanNextGateStatus:
    return CleanNextGateStatus(
        freq=int(row["freq"]),
        trade_date=date.fromisoformat(str(row["trade_date"])),
        clean_partition_path=str(row["clean_partition_path"]),
        source_run_id=str(row["source_run_id"]),
        clean_run_id=str(row["clean_run_id"]),
        write_revision=str(row["write_revision"]),
        status="passed",
        issue_count=0,
        raw_rows=int(row.get("raw_rows") or 0),
        clean_rows=int(row.get("clean_rows") or 0),
        ledger_path=str(row.get("ledger_path") or ""),
        message="M3-C-E 下游重建通知与指标重算队列已写入，正式 clean_next 分区允许下游消费。",
    )


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
