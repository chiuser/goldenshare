from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from lake_console.backend.app.services.duckdb_compute_audit_service import _read_manifest_rows
from lake_console.backend.app.services.duckdb_compute_plan_service import _relpath, _utc_now_iso, _write_json_atomic
from lake_console.backend.app.services.kopia_prewrite_backup_service import (
    KopiaPrewriteBackupError,
    KopiaPrewriteBackupService,
    Runner,
)
from lake_console.backend.app.services.lake_job_state import LakeJobLockService, LakeJobStateStore
from lake_console.backend.app.settings import LakeConsoleSettings


ProgressCallback = Callable[[dict[str, Any]], None]


class DuckDbComputePrewriteBackupService:
    """Create the M3-B Kopia backup for an audited DuckDB compute run.

    This stage intentionally stops before formal publishing: it does not write
    clean_next gate rows, replace formal partitions, or notify downstream queues.
    """

    def __init__(self, *, settings: LakeConsoleSettings, kopia_runner: Runner | None = None) -> None:
        self.settings = settings
        self.lake_root = settings.lake_root.resolve()
        self.kopia_runner = kopia_runner

    def backup_stk_mins_qfq_prewrite(
        self,
        *,
        run_id: str,
        progress_callback: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        manifest_root = self._manifest_root(run_id)
        if not manifest_root.exists():
            raise FileNotFoundError(f"未找到 DuckDB compute run manifest：{_relpath(manifest_root, self.lake_root)}")

        run_payload = _read_json(manifest_root / "run.json")
        self._validate_run_ready_for_backup(run_payload=run_payload)

        existing_backup = self._read_existing_success(manifest_root / "prewrite_backup.json")
        if existing_backup is not None:
            return {
                "run_id": run_id,
                "status": "prewrite_backup_completed",
                "manifest_root": _relpath(manifest_root, self.lake_root),
                "backup": existing_backup,
                "message": "M3-B Kopia 写前备份已存在，本次未重复创建 snapshot。",
                "formal_paths_touched": [],
                "lock_acquired": None,
                "lock_after": LakeJobLockService(LakeJobStateStore(self.lake_root)).get_lock(),
            }

        backup_plan = self._build_backup_plan(run_id=run_id)
        store = LakeJobStateStore(self.lake_root)
        lock_service = LakeJobLockService(store, stale_after_seconds=self.settings.compute_stale_heartbeat_seconds)
        lock_acquired: dict[str, Any] | None = None
        try:
            lock_acquired = lock_service.acquire(run_id=run_id, profile_key="duckdb_compute_stk_mins_qfq")
            _emit_progress(progress_callback, {"event": "prewrite_backup_started", "run_id": run_id})
            _append_event(
                manifest_root / "events.jsonl",
                {
                    "event_type": "prewrite_backup_started",
                    "level": "info",
                    "message": "M3-B 开始 Kopia 写前备份；不发布正式分区，不写 formal gate。",
                    "metrics": {
                        "backup_path_count": len(backup_plan["backup_paths"]),
                        "snapshot_path_count": len(backup_plan["snapshot_paths"]),
                        "path_missing_before_write_count": len(backup_plan["path_missing_before_write"]),
                    },
                },
            )
            backup_service = KopiaPrewriteBackupService(
                lake_root=self.lake_root,
                kopia_bin=self.settings.kopia_bin,
                kopia_config_path=self.settings.kopia_config_path,
                kopia_password=self.settings.kopia_password,
                runner=self.kopia_runner,
            )
            backup = backup_service.create_prewrite_backup(
                run_id=run_id,
                profile_key="duckdb_compute_stk_mins_qfq",
                backup_plan=backup_plan,
            )
            backup_payload = {
                **backup,
                "stage": "m3b_prewrite_backup",
                "formal_paths_touched": [],
                "message": "Kopia 写前备份完成；正式 clean_next、gate、downstream queue 均未修改。",
            }
            _write_json_atomic(manifest_root / "prewrite_backup.json", backup_payload)
            store.write_backup_record(run_id, backup_payload)
            run_payload = {
                **run_payload,
                "status": "prewrite_backup",
                "m3b_prewrite_backup": {
                    "status": "success",
                    "finished_at": _utc_now_iso(),
                    "snapshot_ids": backup_payload.get("snapshot_ids") or [],
                    "snapshot_paths": backup_payload.get("snapshot_paths") or [],
                    "backup_paths": backup_payload.get("backup_paths") or [],
                    "path_missing_before_write": backup_payload.get("path_missing_before_write") or [],
                    "record_path": _relpath(manifest_root / "prewrite_backup.json", self.lake_root),
                },
                "finished_at": None,
                "error": None,
            }
            _write_json_atomic(manifest_root / "run.json", run_payload)
            _append_event(
                manifest_root / "events.jsonl",
                {
                    "event_type": "prewrite_backup_completed",
                    "level": "info",
                    "message": "M3-B Kopia 写前备份完成；下一阶段才能进入 formal publishing。",
                    "metrics": {
                        "snapshot_count": len(backup_payload.get("snapshot_ids") or []),
                        "snapshot_path_count": len(backup_payload.get("snapshot_paths") or []),
                        "backup_path_count": len(backup_payload.get("backup_paths") or []),
                        "path_missing_before_write_count": len(backup_payload.get("path_missing_before_write") or []),
                    },
                },
            )
            lock_service.heartbeat(run_id=run_id)
            _emit_progress(
                progress_callback,
                {
                    "event": "prewrite_backup_completed",
                    "run_id": run_id,
                    "snapshot_count": len(backup_payload.get("snapshot_ids") or []),
                },
            )
            return {
                "run_id": run_id,
                "status": "prewrite_backup_completed",
                "manifest_root": _relpath(manifest_root, self.lake_root),
                "backup": backup_payload,
                "backup_record": _relpath(manifest_root / "prewrite_backup.json", self.lake_root),
                "lake_job_backup_record": _relpath(self.lake_root / "manifest" / "lake_jobs" / "backups" / f"{run_id}-kopia.json", self.lake_root),
                "formal_paths_touched": [],
                "lock_acquired": lock_acquired,
                "lock_after": None,
            }
        except KopiaPrewriteBackupError as exc:
            failed_payload = {
                **run_payload,
                "status": "blocked",
                "m3b_prewrite_backup": {
                    "status": "failed",
                    "failed_at": _utc_now_iso(),
                    "backup_plan": backup_plan,
                    "error_message": str(exc),
                },
                "finished_at": None,
                "error": {
                    "error_code": "LC_COMPUTE_PREWRITE_BACKUP_FAILED",
                    "stage": "prewrite_backup",
                    "message_for_human": "Kopia 写前备份失败，正式数据未被修改。",
                    "technical_detail": str(exc),
                },
            }
            _write_json_atomic(manifest_root / "run.json", failed_payload)
            _append_event(
                manifest_root / "events.jsonl",
                {
                    "event_type": "prewrite_backup_failed",
                    "level": "error",
                    "message": "M3-B Kopia 写前备份失败，正式数据未被修改。",
                    "error": str(exc),
                },
            )
            raise
        finally:
            if lock_acquired is not None:
                lock_service.release(run_id=run_id)

    def _validate_run_ready_for_backup(self, *, run_payload: dict[str, Any]) -> None:
        run_id = str(run_payload.get("run_id") or "")
        if run_payload.get("job_type") != "stk_mins_qfq_clean_next":
            raise RuntimeError(f"不支持的 job_type：{run_payload.get('job_type')}")
        status = str(run_payload.get("status") or "")
        if status == "blocked":
            error = run_payload.get("error") or {}
            if error.get("stage") != "prewrite_backup":
                raise RuntimeError("当前 run 是 blocked，但不是 Kopia 写前备份失败造成，不能进入 M3-B。")
        elif status != "prewrite_backup":
            raise RuntimeError(f"当前 run 状态不能进入 M3-B prewrite backup：{status}")

        manifest_root = self._manifest_root(run_id)
        audit_rows = _read_manifest_rows(manifest_root / "audit_ledger.parquet")
        if audit_rows:
            raise RuntimeError(f"candidate audit ledger 仍有问题，不能创建写前备份：issue_count={len(audit_rows)}")
        publish_rows = _read_manifest_rows(manifest_root / "publish_partitions.parquet")
        if not publish_rows:
            raise RuntimeError("publish_partitions 为空，不能创建写前备份。")
        bad_rows = [
            row
            for row in publish_rows
            if str(row.get("audit_status") or "") != "passed" or str(row.get("publish_status") or "") != "audit_passed"
        ]
        if bad_rows:
            preview = ", ".join(str(row.get("partition_key") or "") for row in bad_rows[:5])
            raise RuntimeError(f"仍有未通过 candidate audit 的发布分区，不能创建写前备份：{preview}")

    def _build_backup_plan(self, *, run_id: str) -> dict[str, Any]:
        protected_paths = [
            "research/stk_mins_by_date_clean_next",
            "manifest/stk_mins_quality/clean_next_partition_gate.parquet",
            "manifest/stk_mins_quality/clean_next_completeness_issue_ledger.parquet",
            f"manifest/duckdb_compute/runs/{run_id}",
            "manifest/downstream_rebuild_requirements/stk_mins.parquet",
            "manifest/source_partition_events/stk_mins.jsonl",
            "manifest/indicator_recalc_queue/stk_mins_macd.parquet",
        ]
        backup_paths: list[str] = []
        missing_paths: list[str] = []
        for relative_path in protected_paths:
            absolute_path = (self.lake_root / relative_path).resolve()
            if not _is_relative_to(absolute_path, self.lake_root):
                raise RuntimeError(f"M3-B 备份路径越界：{relative_path}")
            if absolute_path.exists():
                backup_paths.append(relative_path)
            else:
                missing_paths.append(relative_path)
        if "research/stk_mins_by_date_clean_next" in missing_paths:
            raise RuntimeError("缺少正式 clean_next 根目录，不能创建 qfq 写前备份。")
        return {
            "required": True,
            "provider": "kopia",
            "snapshot_strategy": "duckdb_compute_prewrite_scope",
            "pin_policy": "none",
            "pinned": False,
            "backup_paths": sorted(set(backup_paths)),
            "snapshot_paths": _snapshot_paths_for(backup_paths),
            "path_missing_before_write": sorted(set(missing_paths)),
        }

    def _read_existing_success(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        payload = _read_json(path)
        return payload if payload.get("status") == "success" else None

    def _manifest_root(self, run_id: str) -> Path:
        return self.lake_root / "manifest" / "duckdb_compute" / "runs" / run_id


def _snapshot_paths_for(backup_paths: list[str]) -> list[str]:
    snapshot_paths: set[str] = set()
    for relative_path in backup_paths:
        if relative_path.startswith("research/stk_mins_by_date_clean_next"):
            snapshot_paths.add("research/stk_mins_by_date_clean_next")
        elif relative_path.startswith("manifest/"):
            snapshot_paths.add("manifest")
        else:
            snapshot_paths.add(relative_path)
    return sorted(snapshot_paths)


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON manifest 格式非法：{path}")
    return payload


def _append_event(path: Path, event: dict[str, Any]) -> None:
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


def _emit_progress(progress_callback: ProgressCallback | None, payload: dict[str, Any]) -> None:
    if progress_callback is not None:
        progress_callback(payload)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
