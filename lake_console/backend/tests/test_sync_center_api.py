from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from lake_console.backend.app.api import sync_center
from lake_console.backend.app.main import create_app
from lake_console.backend.app.services.parquet_writer import write_rows_to_parquet
from lake_console.backend.app.settings import LakeConsoleSettings


def test_sync_center_profiles_lock_and_plan_api(monkeypatch, tmp_path: Path) -> None:
    lake_root = tmp_path / "lake"
    lake_root.mkdir()
    _write_calendar(lake_root)
    _patch_settings(monkeypatch, lake_root)
    client = TestClient(create_app())

    profiles_response = client.get("/api/lake/sync/profiles")
    assert profiles_response.status_code == 200
    profiles = profiles_response.json()["items"]
    assert {item["profile_key"] for item in profiles} >= {"prod_db_daily", "stk_mins_sync"}
    assert next(item for item in profiles if item["profile_key"] == "stk_mins_sync")["profile_status"] == "planned"

    lock_response = client.get("/api/lake/sync/lock")
    assert lock_response.status_code == 200
    assert lock_response.json()["status"] == "idle"

    forbidden_response = client.post(
        "/api/lake/sync/profiles/prod_db_daily/plan",
        json={"target_date": "2026-05-14", "dataset_keys": ["daily"], "sql": "select 1"},
    )
    assert forbidden_response.status_code == 422

    plan_response = client.post(
        "/api/lake/sync/profiles/prod_db_daily/plan",
        json={"target_date": "2026-05-14", "dataset_keys": ["daily"]},
    )
    assert plan_response.status_code == 200
    plan = plan_response.json()
    assert plan["profile_key"] == "prod_db_daily"
    assert plan["dataset_plans"][0]["dataset_key"] == "daily"
    assert plan["dataset_plans"][0]["source"] == "prod-raw-db"
    assert "raw_tushare/daily/trade_date=2026-05-14" in plan["backup_plan"]["path_missing_before_write"]
    assert (lake_root / "manifest" / "lake_jobs" / "plans" / f"{plan['plan_token']}.json").exists()

    disabled_response = client.post(
        "/api/lake/sync/profiles/stk_mins_sync/plan",
        json={"target_date": "2026-05-14", "dataset_keys": ["stk_mins"]},
    )
    assert disabled_response.status_code == 400
    assert disabled_response.json()["detail"]["code"] == "PROFILE_DISABLED"


def test_sync_center_run_skeleton_creates_backup_state_and_releases_lock(monkeypatch, tmp_path: Path) -> None:
    lake_root = tmp_path / "lake"
    (lake_root / "raw_tushare" / "daily" / "trade_date=2026-05-14").mkdir(parents=True)
    _write_calendar(lake_root)
    _patch_settings(monkeypatch, lake_root)
    captured: dict[str, Any] = {}

    class FakeBackupService:
        def __init__(self, **kwargs: Any) -> None:
            captured["init"] = kwargs

        def create_prewrite_backup(self, *, run_id: str, profile_key: str, backup_plan: dict[str, Any]) -> dict[str, Any]:
            captured["backup_plan"] = backup_plan
            return {
                "run_id": run_id,
                "profile_key": profile_key,
                "provider": "kopia",
                "status": "success",
                "pin_policy": "none",
                "created_at": "2026-05-14T00:00:00+00:00",
                "snapshot_ids": ["snapshot-001"],
                "snapshots": [],
                "backup_paths": backup_plan["backup_paths"],
                "path_missing_before_write": backup_plan["path_missing_before_write"],
            }

    monkeypatch.setattr(sync_center, "KopiaPrewriteBackupService", FakeBackupService)
    client = TestClient(create_app())
    plan = client.post(
        "/api/lake/sync/profiles/prod_db_daily/plan",
        json={"target_date": "2026-05-14", "dataset_keys": ["daily"]},
    ).json()

    run_response = client.post(
        "/api/lake/sync/runs",
        json={"plan_token": plan["plan_token"], "confirmed_backup_required": True, "confirmed_no_sql": True},
    )
    assert run_response.status_code == 200
    run = run_response.json()
    assert run["status"] == "blocked"
    assert run["lock"]["status"] == "idle"
    assert captured["backup_plan"]["backup_paths"] == ["raw_tushare/daily/trade_date=2026-05-14"]

    detail_response = client.get(run["detail_url"])
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["status"] == "blocked"
    assert detail["backup"]["snapshot_ids"] == ["snapshot-001"]
    assert detail["errors"][0]["code"] == "EXECUTION_NOT_IMPLEMENTED"

    events_response = client.get(run["events_url"])
    assert events_response.status_code == 200
    event_types = [item["event_type"] for item in events_response.json()["items"]]
    assert event_types == ["run_started", "lock_acquired", "backup_started", "backup_completed", "run_blocked"]


def test_sync_center_run_rejects_plan_with_blockers(monkeypatch, tmp_path: Path) -> None:
    lake_root = tmp_path / "lake"
    lake_root.mkdir()
    _patch_settings(monkeypatch, lake_root)
    client = TestClient(create_app())
    plan = client.post(
        "/api/lake/sync/profiles/lake_reference_refresh/plan",
        json={"dataset_keys": ["trade_cal"]},
    ).json()
    assert plan["blockers"][0]["dataset_key"] == "trade_cal"

    run_response = client.post(
        "/api/lake/sync/runs",
        json={"plan_token": plan["plan_token"], "confirmed_backup_required": True, "confirmed_no_sql": True},
    )
    assert run_response.status_code == 409
    assert run_response.json()["detail"]["code"] == "PLAN_BLOCKED"


def _patch_settings(monkeypatch, lake_root: Path) -> None:
    monkeypatch.setattr(
        sync_center,
        "load_settings",
        lambda: LakeConsoleSettings(
            lake_root=lake_root,
            tushare_token=None,
        ),
    )


def _write_calendar(lake_root: Path) -> None:
    write_rows_to_parquet(
        [{"cal_date": "2026-05-14", "is_open": True}],
        lake_root / "manifest" / "trading_calendar" / "tushare_trade_cal.parquet",
    )
