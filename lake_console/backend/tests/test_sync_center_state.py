from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from lake_console.backend.app.services.lake_job_state import LakeJobLockBusyError, LakeJobLockService, LakeJobStateStore


def test_lake_job_state_store_writes_plans_runs_and_events(tmp_path: Path) -> None:
    lake_root = tmp_path / "lake"
    store = LakeJobStateStore(lake_root)
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()

    store.write_plan({"plan_token": "pln_test", "plan_token_expires_at": expires_at, "profile_key": "prod_db_daily"})
    assert store.read_plan("pln_test")["profile_key"] == "prod_db_daily"
    assert (lake_root / "manifest" / "lake_jobs" / "plans" / "pln_test.json").exists()

    store.write_run(
        {
            "run_id": "run_test",
            "profile_key": "prod_db_daily",
            "plan_token": "pln_test",
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
        }
    )
    assert store.read_run("run_test")["status"] == "running"

    first = store.append_event("run_test", {"event_type": "run_started", "message": "start"})
    second = store.append_event("run_test", {"event_type": "backup_started", "message": "backup"})
    assert first["seq"] == 1
    assert second["seq"] == 2
    listing = store.list_events("run_test", cursor=1, limit=10)
    assert listing["items"][0]["event_type"] == "backup_started"
    assert listing["next_cursor"] == 2


def test_lake_job_lock_blocks_running_and_allows_stale_release(tmp_path: Path) -> None:
    store = LakeJobStateStore(tmp_path / "lake")
    lock_service = LakeJobLockService(store, stale_after_seconds=1)

    lock = lock_service.acquire(run_id="run_1", profile_key="prod_db_daily")
    assert lock["status"] == "running"

    with pytest.raises(LakeJobLockBusyError):
        lock_service.acquire(run_id="run_2", profile_key="prod_db_daily")

    old_timestamp = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
    store._write_json(
        store.lock_path,
        {
            **lock,
            "last_heartbeat_at": old_timestamp,
            "stale_after_seconds": 1,
            "status": "running",
        },
    )
    stale = lock_service.get_lock()
    assert stale["status"] == "stale"
    assert stale["can_release_stale"] is True

    released = lock_service.release_stale(reason="test stale cleanup")
    assert released["run_id"] == "run_1"
    assert lock_service.get_lock()["status"] == "idle"
