from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from lake_console.backend.app.services.duckdb_compute_plan_service import _relpath, _utc_now_iso, _write_json_atomic
from lake_console.backend.app.services.lake_job_state import LakeJobLockService, LakeJobStateStore
from lake_console.backend.app.services.stk_mins_clean_next_gate import CleanNextPartitionGateService
from lake_console.backend.app.settings import LakeConsoleSettings


PUBLISH_STARTED_STATUSES = {"publishing", "published", "formal_audit_failed"}
RUN_TERMINAL_STATUSES = {"abandoned", "published"}


class DuckDbComputeRunLifecycleService:
    """Lifecycle operations for DuckDB compute run manifests."""

    def __init__(self, *, settings: LakeConsoleSettings) -> None:
        self.settings = settings
        self.lake_root = settings.lake_root.resolve()

    def abandon_stk_mins_qfq_run(self, *, run_id: str, reason: str) -> dict[str, Any]:
        manifest_root = self.lake_root / "manifest" / "duckdb_compute" / "runs" / run_id
        if not manifest_root.exists():
            raise FileNotFoundError(f"未找到 DuckDB compute run manifest：{_relpath(manifest_root, self.lake_root)}")

        run_file = manifest_root / "run.json"
        run_payload = _read_json(run_file)
        blockers = self._abandon_blockers(run_id=run_id, manifest_root=manifest_root, run_payload=run_payload)
        if blockers:
            return {
                "operation": "abandon_stk_mins_qfq_run",
                "run_id": run_id,
                "status": "blocked",
                "ready": False,
                "blockers": blockers,
                "formal_paths_touched": [],
                "message": "该 run 已进入或疑似进入正式发布链路，拒绝废弃。",
            }

        now = _utc_now_iso()
        updated = {
            **run_payload,
            "status": "abandoned",
            "abandoned_at": now,
            "abandon_reason": reason,
            "finished_at": now,
            "error": None,
        }
        _write_json_atomic(run_file, updated)
        _append_event(
            manifest_root / "events.jsonl",
            {
                "event_type": "run_abandoned",
                "level": "warning",
                "message": "DuckDB compute run 已人工废弃；未修改正式 clean_next、gate 或 downstream queue。",
                "metrics": {
                    "previous_status": run_payload.get("status"),
                    "reason": reason,
                },
            },
        )
        return {
            "operation": "abandon_stk_mins_qfq_run",
            "run_id": run_id,
            "status": "abandoned",
            "ready": True,
            "previous_status": run_payload.get("status"),
            "manifest_root": _relpath(manifest_root, self.lake_root),
            "formal_paths_touched": [],
            "message": "run 已标记为 abandoned；candidate/tmp/backup 记录保留用于追溯，readiness 不再把它视为 active run。",
        }

    def _abandon_blockers(self, *, run_id: str, manifest_root: Path, run_payload: dict[str, Any]) -> list[dict[str, Any]]:
        blockers: list[dict[str, Any]] = []
        status = str(run_payload.get("status") or "")
        if status in RUN_TERMINAL_STATUSES:
            blockers.append(
                {
                    "code": "run_already_terminal",
                    "message": "run 已经是终态，不能重复废弃。",
                    "status": status,
                }
            )
        if status == "running":
            blockers.append(
                {
                    "code": "run_may_still_be_running",
                    "message": "run 当前状态是 running，不能用 abandon 处理；需要先确认进程和锁。",
                }
            )
        if status in {"publishing", "published"}:
            blockers.append(
                {
                    "code": "run_already_entered_publish_stage",
                    "message": "run 已进入正式发布阶段，不能按未发布样本 run 废弃。",
                    "status": status,
                }
            )
        for stage_key in ("m3c_c_gate_publishing", "m3c_d_formal_publish", "m3c_e_downstream_and_gate_passed"):
            if stage_key in run_payload:
                blockers.append(
                    {
                        "code": "publish_stage_state_exists",
                        "message": "run.json 中已经存在正式发布阶段状态，不能废弃。",
                        "stage": stage_key,
                    }
                )

        publish_partitions = manifest_root / "publish_partitions.parquet"
        if publish_partitions.exists():
            rows = pd.read_parquet(publish_partitions).to_dict("records")
            started = [
                {
                    "partition_key": row.get("partition_key"),
                    "publish_status": row.get("publish_status"),
                }
                for row in rows
                if str(row.get("publish_status") or "") in PUBLISH_STARTED_STATUSES
            ]
            if started:
                blockers.append(
                    {
                        "code": "publish_partitions_already_started",
                        "message": "publish_partitions 已经显示该 run 进入发布或发布失败阶段，不能废弃。",
                        "samples": started[:10],
                    }
                )

        gate_refs = []
        for row in CleanNextPartitionGateService(lake_root=self.lake_root).read_statuses():
            row_text = json.dumps(row, ensure_ascii=False, default=str)
            if run_id in row_text:
                gate_refs.append(
                    {
                        "partition_key": row.get("partition_key"),
                        "status": row.get("status"),
                        "write_revision": row.get("write_revision"),
                    }
                )
        if gate_refs:
            blockers.append(
                {
                    "code": "formal_gate_references_run",
                    "message": "clean_next formal gate 已经引用该 run，不能按未发布 run 废弃。",
                    "samples": gate_refs[:10],
                }
            )

        lock = LakeJobLockService(
            LakeJobStateStore(self.lake_root),
            stale_after_seconds=self.settings.compute_stale_heartbeat_seconds,
        ).get_lock()
        if lock.get("status") != "idle":
            blockers.append(
                {
                    "code": "lake_write_lock_not_idle",
                    "message": "当前 Lake 写入锁不是 idle，不能废弃 run。",
                    "lock": lock,
                }
            )
        return blockers


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _append_event(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    seq = 1
    if path.exists():
        seq = len(path.read_text(encoding="utf-8").splitlines()) + 1
    event = {"created_at": _utc_now_iso(), **payload, "seq": seq}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
