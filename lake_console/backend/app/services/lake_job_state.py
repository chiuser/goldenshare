from __future__ import annotations

import json
import os
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from lake_console.backend.app.services.sync_center_profiles import STALE_AFTER_SECONDS


class LakeJobStateError(RuntimeError):
    pass


class LakeJobLockBusyError(LakeJobStateError):
    def __init__(self, lock_payload: dict[str, Any]) -> None:
        super().__init__("已有 Lake 写入任务运行或 stale，不能启动新任务。")
        self.lock_payload = lock_payload


class PlanNotFoundError(LakeJobStateError):
    pass


class PlanExpiredError(LakeJobStateError):
    pass


class LakeJobStateStore:
    def __init__(self, lake_root: Path) -> None:
        self.lake_root = lake_root
        self.root = lake_root / "manifest" / "lake_jobs"
        self.plans_dir = self.root / "plans"
        self.runs_dir = self.root / "runs"
        self.events_dir = self.root / "events"
        self.backups_dir = self.root / "backups"
        self.current_path = self.root / "current.json"
        self.lock_path = self.root / "active_task.lock"

    def ensure_dirs(self) -> None:
        for path in (self.plans_dir, self.runs_dir, self.events_dir, self.backups_dir):
            path.mkdir(parents=True, exist_ok=True)

    def write_plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.ensure_dirs()
        token = payload["plan_token"]
        self._write_json(self.plans_dir / f"{token}.json", payload)
        return payload

    def read_plan(self, plan_token: str) -> dict[str, Any]:
        path = self.plans_dir / f"{plan_token}.json"
        if not path.exists():
            raise PlanNotFoundError(f"未找到 plan_token：{plan_token}")
        payload = self._read_json(path)
        expires_at = _parse_datetime(payload.get("plan_token_expires_at"))
        if expires_at is not None and _utc_now() > expires_at:
            raise PlanExpiredError(f"plan_token 已过期：{plan_token}")
        return payload

    def write_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.ensure_dirs()
        self._write_json(self.runs_dir / f"{payload['run_id']}.json", payload)
        return payload

    def read_run(self, run_id: str) -> dict[str, Any] | None:
        path = self.runs_dir / f"{run_id}.json"
        if not path.exists():
            return None
        return self._read_json(path)

    def write_current(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.ensure_dirs()
        self._write_json(self.current_path, payload)
        return payload

    def read_current(self) -> dict[str, Any]:
        if not self.current_path.exists():
            return {
                "active_run_id": None,
                "status": "idle",
                "profile_key": None,
                "started_at": None,
                "updated_at": _utc_now_iso(),
                "progress_summary": "当前没有运行中的 Lake 写入任务。",
                "current_dataset_key": None,
                "current_partition": None,
                "current_stage_key": None,
                "requires_confirmation": False,
                "next_action": None,
            }
        return self._read_json(self.current_path)

    def append_event(self, run_id: str, event: dict[str, Any]) -> dict[str, Any]:
        self.ensure_dirs()
        path = self.events_dir / f"{run_id}.jsonl"
        seq = self._next_event_seq(path)
        payload = {
            "seq": seq,
            "event_id": f"evt_{run_id}_{seq:06d}_{uuid4().hex[:8]}",
            "created_at": _utc_now_iso(),
            "level": "info",
            "stage_key": None,
            "dataset_key": None,
            "partition_locator": None,
            "metrics": {},
            "error": None,
            **event,
        }
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        return payload

    def list_events(self, run_id: str, *, cursor: int = 0, limit: int = 200) -> dict[str, Any]:
        path = self.events_dir / f"{run_id}.jsonl"
        if not path.exists():
            return {"items": [], "next_cursor": cursor}
        bounded_limit = min(max(limit, 1), 1000)
        items: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue
                event = json.loads(line)
                if int(event.get("seq", 0)) <= cursor:
                    continue
                items.append(event)
                if len(items) >= bounded_limit:
                    break
        next_cursor = int(items[-1]["seq"]) if items else cursor
        return {"items": items, "next_cursor": next_cursor}

    def write_backup_record(self, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.ensure_dirs()
        self._write_json(self.backups_dir / f"{run_id}-kopia.json", payload)
        return payload

    def _read_json(self, path: Path) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
        if not isinstance(payload, dict):
            raise LakeJobStateError(f"状态文件格式非法：{path}")
        return payload

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
        with tmp_path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, sort_keys=True, indent=2)
            file.write("\n")
        tmp_path.replace(path)

    def _next_event_seq(self, path: Path) -> int:
        if not path.exists():
            return 1
        last_seq = 0
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                if line.strip():
                    last_seq = int(json.loads(line).get("seq", last_seq))
        return last_seq + 1


class LakeJobLockService:
    def __init__(self, store: LakeJobStateStore, *, stale_after_seconds: int = STALE_AFTER_SECONDS) -> None:
        self.store = store
        self.stale_after_seconds = stale_after_seconds

    def get_lock(self) -> dict[str, Any]:
        if not self.store.lock_path.exists():
            return {
                "status": "idle",
                "run_id": None,
                "profile_key": None,
                "owner_pid": None,
                "owner_host": None,
                "acquired_at": None,
                "last_heartbeat_at": None,
                "stale_after_seconds": self.stale_after_seconds,
                "can_release_stale": False,
            }
        payload = self.store._read_json(self.store.lock_path)
        status = "stale" if self._is_stale(payload) else "running"
        return {
            **payload,
            "status": status,
            "stale_after_seconds": int(payload.get("stale_after_seconds") or self.stale_after_seconds),
            "can_release_stale": status == "stale",
        }

    def acquire(self, *, run_id: str, profile_key: str) -> dict[str, Any]:
        current = self.get_lock()
        if current["status"] in {"running", "stale"}:
            raise LakeJobLockBusyError(current)
        payload = {
            "run_id": run_id,
            "profile_key": profile_key,
            "owner_pid": os.getpid(),
            "owner_host": socket.gethostname(),
            "acquired_at": _utc_now_iso(),
            "last_heartbeat_at": _utc_now_iso(),
            "stale_after_seconds": self.stale_after_seconds,
            "status": "running",
        }
        self.store.ensure_dirs()
        self.store._write_json(self.store.lock_path, payload)
        return self.get_lock()

    def heartbeat(self, *, run_id: str) -> dict[str, Any]:
        current = self.get_lock()
        if current["run_id"] != run_id:
            raise LakeJobStateError(f"当前 lock 不属于 run_id：{run_id}")
        payload = {**current, "last_heartbeat_at": _utc_now_iso(), "status": "running"}
        self.store._write_json(self.store.lock_path, payload)
        return self.get_lock()

    def release(self, *, run_id: str) -> None:
        current = self.get_lock()
        if current["status"] == "idle":
            return
        if current["run_id"] != run_id:
            raise LakeJobStateError(f"不能释放其他任务的 lock：current={current['run_id']} requested={run_id}")
        self.store.lock_path.unlink(missing_ok=True)

    def release_stale(self, *, reason: str) -> dict[str, Any]:
        current = self.get_lock()
        if current["status"] != "stale":
            raise LakeJobStateError("当前 lock 不是 stale，不能释放。")
        released = {
            **current,
            "released_at": _utc_now_iso(),
            "release_reason": reason,
        }
        self.store.lock_path.unlink(missing_ok=True)
        return released

    def _is_stale(self, payload: dict[str, Any]) -> bool:
        last_seen = _parse_datetime(payload.get("last_heartbeat_at"))
        if last_seen is None:
            return True
        stale_after = int(payload.get("stale_after_seconds") or self.stale_after_seconds)
        return (_utc_now() - last_seen).total_seconds() > stale_after


def new_plan_token() -> str:
    return f"pln_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid4().hex[:8]}"


def new_run_id(profile_key: str) -> str:
    suffix = profile_key.replace("_", "-")
    return f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{suffix}-{uuid4().hex[:6]}"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
