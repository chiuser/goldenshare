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
    (lake_root / "raw_tushare" / "bse_mapping" / "current").mkdir(parents=True)
    (lake_root / "raw_tushare" / "bse_mapping" / "current" / "part-000.parquet").write_text("old", encoding="utf-8")
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

    class FakeRunner:
        @classmethod
        def validate_plan(cls, *, plan: dict[str, Any]) -> None:
            return None

        def __init__(self, *, settings, progress):  # type: ignore[no-untyped-def]
            self.progress = progress

        def run(self, *, plan: dict[str, Any]) -> dict[str, Any]:
            self.progress({"event_type": "dataset_started", "dataset_key": "bse_mapping", "message": "start"})
            self.progress(
                {
                    "event_type": "dataset_completed",
                    "dataset_key": "bse_mapping",
                    "message": "done",
                    "metrics": {"fetched_rows": 1, "written_rows": 1},
                }
            )
            return {
                "status": "success",
                "dataset_results": [
                    {
                        "dataset_key": "bse_mapping",
                        "status": "success",
                        "fetched_rows": 1,
                        "written_rows": 1,
                    }
                ],
                "progress": {
                    "summary": "bse_mapping done",
                    "current_dataset_key": "bse_mapping",
                    "current_partition": "current",
                },
            }

    monkeypatch.setattr(sync_center, "SyncProfileRunner", FakeRunner)
    client = TestClient(create_app())
    plan = client.post(
        "/api/lake/sync/profiles/prod_db_snapshot_refresh/plan",
        json={"dataset_keys": ["bse_mapping"]},
    ).json()

    run_response = client.post(
        "/api/lake/sync/runs",
        json={"plan_token": plan["plan_token"], "confirmed_backup_required": True, "confirmed_no_sql": True},
    )
    assert run_response.status_code == 200
    run = run_response.json()
    assert run["status"] == "success"
    assert run["lock"]["status"] == "idle"
    assert captured["backup_plan"]["backup_paths"] == ["raw_tushare/bse_mapping/current/part-000.parquet"]

    detail_response = client.get(run["detail_url"])
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["status"] == "success"
    assert detail["backup"]["snapshot_ids"] == ["snapshot-001"]
    assert detail["dataset_results"][0]["written_rows"] == 1
    assert detail["errors"] == []

    events_response = client.get(run["events_url"])
    assert events_response.status_code == 200
    event_types = [item["event_type"] for item in events_response.json()["items"]]
    assert event_types == [
        "run_started",
        "lock_acquired",
        "backup_started",
        "backup_completed",
        "execution_started",
        "dataset_started",
        "dataset_completed",
        "run_completed",
    ]


def test_sync_center_run_rejects_plan_with_blockers(monkeypatch, tmp_path: Path) -> None:
    lake_root = tmp_path / "lake"
    lake_root.mkdir()
    _patch_settings(monkeypatch, lake_root)
    client = TestClient(create_app())
    plan = client.post(
        "/api/lake/sync/profiles/prod_db_daily/plan",
        json={"dataset_keys": ["daily"]},
    ).json()
    assert plan["blockers"][0]["dataset_key"] == "daily"

    run_response = client.post(
        "/api/lake/sync/runs",
        json={"plan_token": plan["plan_token"], "confirmed_backup_required": True, "confirmed_no_sql": True},
    )
    assert run_response.status_code == 409
    assert run_response.json()["detail"]["code"] == "PLAN_BLOCKED"


def test_sync_center_run_returns_structured_unexpected_error(monkeypatch, tmp_path: Path) -> None:
    lake_root = tmp_path / "lake"
    (lake_root / "raw_tushare" / "bse_mapping" / "current").mkdir(parents=True)
    (lake_root / "raw_tushare" / "bse_mapping" / "current" / "part-000.parquet").write_text("old", encoding="utf-8")
    _write_calendar(lake_root)
    _patch_settings(monkeypatch, lake_root)

    class FakeBackupService:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def create_prewrite_backup(self, *, run_id: str, profile_key: str, backup_plan: dict[str, Any]) -> dict[str, Any]:
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

    class FailingRunner:
        @classmethod
        def validate_plan(cls, *, plan: dict[str, Any]) -> None:
            return None

        def __init__(self, *, settings, progress):  # type: ignore[no-untyped-def]
            pass

        def run(self, *, plan: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("缺少 Parquet 写入依赖。请先安装依赖。")

    monkeypatch.setattr(sync_center, "SyncProfileRunner", FailingRunner)
    client = TestClient(create_app())
    plan = client.post(
        "/api/lake/sync/profiles/prod_db_snapshot_refresh/plan",
        json={"dataset_keys": ["bse_mapping"]},
    ).json()

    run_response = client.post(
        "/api/lake/sync/runs",
        json={"plan_token": plan["plan_token"], "confirmed_backup_required": True, "confirmed_no_sql": True},
    )
    assert run_response.status_code == 500
    detail = run_response.json()["detail"]
    assert detail["code"] == "SYNC_PROFILE_RUNNER_UNEXPECTED_ERROR"
    assert "Parquet" in detail["message"]
    assert detail["context"]["run_id"]
    assert client.get("/api/lake/sync/lock").json()["status"] == "idle"

    run_detail = client.get(f"/api/lake/sync/runs/{detail['context']['run_id']}").json()
    assert run_detail["status"] == "failed"
    assert run_detail["errors"][0]["code"] == "SYNC_PROFILE_RUNNER_UNEXPECTED_ERROR"


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
