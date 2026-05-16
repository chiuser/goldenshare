from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from lake_console.backend.app.api import sync_center
from lake_console.backend.app.main import create_app
from lake_console.backend.app.services.lake_job_state import LakeJobStateStore
from lake_console.backend.app.services.parquet_writer import write_rows_to_parquet
from lake_console.backend.app.services.prod_raw_event_date_db import EventDatePartitionCount
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
    assert {item["profile_key"] for item in profiles} >= {"prod_db_daily", "prod_db_event_date", "stk_mins_sync"}
    assert next(item for item in profiles if item["profile_key"] == "prod_db_event_date")["profile_status"] == "enabled"
    assert next(item for item in profiles if item["profile_key"] == "stk_mins_sync")["profile_status"] == "enabled"

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

    invalid_stk_mins_response = client.post(
        "/api/lake/sync/profiles/stk_mins_sync/plan",
        json={"target_date": "2026-05-14", "dataset_keys": ["stk_mins"]},
    )
    assert invalid_stk_mins_response.status_code == 400
    assert invalid_stk_mins_response.json()["detail"]["code"] == "INVALID_STK_MINS_PIPELINE_PLAN"


def test_prod_db_event_date_plan_returns_event_partitions(monkeypatch, tmp_path: Path) -> None:
    lake_root = tmp_path / "lake"
    (lake_root / "raw_tushare" / "anns_d" / "event_date=2026-05-13").mkdir(parents=True)
    _patch_settings(monkeypatch, lake_root, prod_raw_db_url="postgresql://readonly@example/raw")
    captured: dict[str, Any] = {}

    def fake_partition_counts(*, database_url: str | None, dataset_key: str, start_date: date, end_date: date):
        captured["database_url"] = database_url
        captured["dataset_key"] = dataset_key
        captured["start_date"] = start_date
        captured["end_date"] = end_date
        return [
            EventDatePartitionCount(event_date=date(2026, 5, 13), source_row_count=38280),
            EventDatePartitionCount(event_date=date(2026, 5, 15), source_row_count=21940),
        ]

    monkeypatch.setattr(
        "lake_console.backend.app.sync.planners.event_date.fetch_event_date_partition_counts",
        fake_partition_counts,
    )
    monkeypatch.setattr(
        "lake_console.backend.app.sync.planners.event_date.fetch_event_date_null_count",
        lambda **_: 0,
    )
    client = TestClient(create_app())

    plan_response = client.post(
        "/api/lake/sync/profiles/prod_db_event_date/plan",
        json={"start_date": "2026-05-13", "end_date": "2026-05-15", "dataset_keys": ["anns_d"]},
    )

    assert plan_response.status_code == 200
    plan = plan_response.json()
    assert captured == {
        "database_url": "postgresql://readonly@example/raw",
        "dataset_key": "anns_d",
        "start_date": date(2026, 5, 13),
        "end_date": date(2026, 5, 15),
    }
    assert plan["profile_key"] == "prod_db_event_date"
    assert plan["affected_event_dates"] == ["2026-05-13", "2026-05-15"]
    assert plan["blockers"] == []
    dataset_plan = plan["dataset_plans"][0]
    assert dataset_plan["dataset_key"] == "anns_d"
    assert dataset_plan["date_axis"] == "event_date"
    assert dataset_plan["source_date_field"] == "ann_date"
    assert dataset_plan["zero_row_dates"] == ["2026-05-14"]
    assert dataset_plan["source_row_count"] == 60220
    assert dataset_plan["event_date_partitions"] == [
        {
            "event_date": "2026-05-13",
            "source_row_count": 38280,
            "write_path": "raw_tushare/anns_d/event_date=2026-05-13",
        },
        {
            "event_date": "2026-05-15",
            "source_row_count": 21940,
            "write_path": "raw_tushare/anns_d/event_date=2026-05-15",
        },
    ]
    assert plan["backup_plan"]["backup_paths"] == ["raw_tushare/anns_d/event_date=2026-05-13"]
    assert plan["backup_plan"]["snapshot_paths"] == ["raw_tushare/anns_d"]
    assert plan["backup_plan"]["path_missing_before_write"] == ["raw_tushare/anns_d/event_date=2026-05-15"]


def test_prod_db_event_date_plan_requires_explicit_dataset(monkeypatch, tmp_path: Path) -> None:
    lake_root = tmp_path / "lake"
    lake_root.mkdir()
    _patch_settings(monkeypatch, lake_root, prod_raw_db_url="postgresql://readonly@example/raw")
    client = TestClient(create_app())

    plan_response = client.post(
        "/api/lake/sync/profiles/prod_db_event_date/plan",
        json={"target_date": "2026-05-15"},
    )

    assert plan_response.status_code == 400
    assert plan_response.json()["detail"]["code"] == "DATASET_NOT_ALLOWED"
    assert "必须显式选择" in plan_response.json()["detail"]["message"]


def test_prod_db_event_date_plan_blocks_no_row_window(monkeypatch, tmp_path: Path) -> None:
    lake_root = tmp_path / "lake"
    lake_root.mkdir()
    _patch_settings(monkeypatch, lake_root, prod_raw_db_url="postgresql://readonly@example/raw")
    monkeypatch.setattr(
        "lake_console.backend.app.sync.planners.event_date.fetch_event_date_partition_counts",
        lambda **_: [],
    )
    monkeypatch.setattr(
        "lake_console.backend.app.sync.planners.event_date.fetch_event_date_null_count",
        lambda **_: 0,
    )
    client = TestClient(create_app())

    plan_response = client.post(
        "/api/lake/sync/profiles/prod_db_event_date/plan",
        json={"target_date": "2026-05-15", "dataset_keys": ["irm_qa_sh"]},
    )

    assert plan_response.status_code == 200
    plan = plan_response.json()
    assert plan["dataset_plans"][0]["status"] == "no_rows_no_write"
    assert plan["dataset_plans"][0]["write_paths"] == []
    assert plan["blockers"][0]["code"] == "NO_EVENT_DATE_ROWS"
    assert plan["summary"]["write_path_count"] == 0


def test_stk_mins_sync_plan_returns_readonly_pipeline_contract(monkeypatch, tmp_path: Path) -> None:
    lake_root = tmp_path / "lake"
    lake_root.mkdir()
    _write_calendar(lake_root, dates=["2026-05-08", "2026-05-11", "2026-05-12", "2026-05-13", "2026-05-14"])
    _write_universe(lake_root)
    _patch_settings(monkeypatch, lake_root)
    _run_background_inline(monkeypatch)
    _mock_stk_mins_pipeline_sync(monkeypatch)
    _mock_stk_mins_pipeline_derived(monkeypatch)
    _mock_stk_mins_pipeline_research(monkeypatch)
    client = TestClient(create_app())

    plan_response = client.post(
        "/api/lake/sync/profiles/stk_mins_sync/plan",
        json={
            "start_date": "2026-05-08",
            "end_date": "2026-05-14",
            "dataset_keys": ["stk_mins"],
            "freqs": [1, 5, 15, 30, 60],
            "scope": "all_market",
            "mode": "manual_gate",
        },
    )

    assert plan_response.status_code == 200
    plan = plan_response.json()
    assert plan["profile_key"] == "stk_mins_sync"
    assert plan["profile"]["profile_status"] == "enabled"
    assert plan["affected_trade_dates"] == ["2026-05-08", "2026-05-11", "2026-05-12", "2026-05-13", "2026-05-14"]
    assert plan["affected_months"] == ["2026-05"]
    assert plan["normalized_parameters"]["freqs"] == [1, 5, 15, 30, 60]
    assert plan["normalized_parameters"]["derived_freqs"] == [90, 120]
    assert plan["normalized_parameters"]["research_freqs"] == [1, 5, 15, 30, 60, 90, 120]
    assert plan["dataset_plans"][0]["mode"] == "staged_pipeline_plan"
    assert plan["dataset_plans"][0]["status"] == "plan_only"
    assert plan["blockers"] == []
    assert plan["warnings"][0]["code"] == "PIPELINE_REQUIRES_MANUAL_CONFIRMATIONS"

    stages = {item["stage_key"]: item for item in plan["pipeline_stages"]}
    assert list(stages) == [
        "plan_preflight",
        "prewrite_backup",
        "raw_sync",
        "clean_next_refresh",
        "clean_next_review",
        "derived_90_120_build",
        "derived_review",
        "research_month_rebuild",
        "final_validation",
    ]
    assert stages["plan_preflight"]["stage_status"] == "passed"
    assert stages["plan_preflight"]["stage_status_label"] == "已通过"
    assert stages["clean_next_review"]["requires_confirmation"] is True
    assert stages["clean_next_review"]["next_action"]["label"] == "继续生成 90/120"
    assert stages["derived_review"]["requires_confirmation"] is True
    assert stages["derived_review"]["next_action"]["action"] == "continue"
    assert stages["derived_review"]["next_action"]["label"] == "继续重排 research by month"

    missing_paths = plan["backup_plan"]["path_missing_before_write"]
    assert "raw_tushare/stk_mins_by_date/freq=1/trade_date=2026-05-08" in missing_paths
    assert "research/stk_mins_by_date_clean_next/freq=60/trade_date=2026-05-14" in missing_paths
    assert "derived/stk_mins_by_date/freq=90/trade_date=2026-05-08" in missing_paths
    assert "derived/stk_mins_by_date/freq=120/trade_date=2026-05-14" in missing_paths
    assert "research/stk_mins_by_symbol_month/freq=120/trade_month=2026-05" in missing_paths
    assert (lake_root / "manifest" / "lake_jobs" / "plans" / f"{plan['plan_token']}.json").exists()

    run_response = client.post(
        "/api/lake/sync/runs",
        json={"plan_token": plan["plan_token"], "confirmed_backup_required": True, "confirmed_no_sql": True},
    )
    assert run_response.status_code == 200
    run = run_response.json()
    assert run["status"] == "waiting_confirmation"
    assert run["run_status"] == "waiting_confirmation"
    assert run["lock"]["status"] == "idle"

    detail_response = client.get(run["detail_url"])
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["run_status"] == "waiting_confirmation"
    assert detail["current_stage_key"] == "clean_next_review"
    assert detail["requires_confirmation"] is True
    assert detail["next_action"]["label"] == "继续生成 90/120"
    assert detail["backup"]["status"] == "success"
    assert detail["dataset_results"][0]["dataset_key"] == "stk_mins"
    assert detail["pipeline_stages"][0]["stage_key"] == "plan_preflight"
    assert detail["pipeline_stages"][0]["stage_status"] == "passed"
    backup_stage = next(stage for stage in detail["pipeline_stages"] if stage["stage_key"] == "prewrite_backup")
    assert backup_stage["stage_status"] == "passed"
    assert backup_stage["metrics"]["path_missing_before_write_count"] >= len(missing_paths)
    raw_stage = next(stage for stage in detail["pipeline_stages"] if stage["stage_key"] == "raw_sync")
    clean_stage = next(stage for stage in detail["pipeline_stages"] if stage["stage_key"] == "clean_next_refresh")
    assert raw_stage["stage_status"] == "passed"
    assert clean_stage["stage_status"] == "passed"
    assert clean_stage["display_summary"] == "clean_next/gate 刷新完成：1 个分区已通过。"
    assert clean_stage["metrics"]["affected_partition_count"] == 1

    events_response = client.get(run["events_url"])
    assert events_response.status_code == 200
    events = events_response.json()["items"]
    assert [item["event_type"] for item in events] == [
        "pipeline_run_created",
        "backup_started",
        "backup_completed",
        "raw_sync_started",
        "raw_sync_progress",
        "clean_next_review_waiting",
    ]
    assert events[0]["stage_key"] == "prewrite_backup"
    assert events[0]["metrics"]["state_only"] is True
    assert events[-1]["stage_key"] == "clean_next_review"

    continue_response = client.post(
        f"/api/lake/sync/runs/{run['run_id']}/continue",
        json={"confirm_continue": True, "operator": "tester"},
    )
    assert continue_response.status_code == 200
    continued = continue_response.json()
    assert continued["run_status"] == "waiting_confirmation"
    assert continued["current_stage_key"] == "derived_review"
    derived_stage = next(stage for stage in continued["pipeline_stages"] if stage["stage_key"] == "derived_90_120_build")
    assert derived_stage["stage_status"] == "passed"
    assert derived_stage["metrics"]["written_rows"] == 80
    assert continued["next_action"]["action"] == "continue"
    assert continued["next_action"]["label"] == "继续重排 research by month"

    continued_events = client.get(run["events_url"]).json()["items"]
    assert [item["event_type"] for item in continued_events][-4:] == [
        "pipeline_continue_confirmed",
        "derived_90_120_started",
        "derived_90_120_progress",
        "derived_review_waiting",
    ]
    assert client.get("/api/lake/sync/lock").json()["status"] == "idle"

    final_response = client.post(
        f"/api/lake/sync/runs/{run['run_id']}/continue",
        json={"confirm_continue": True, "operator": "tester"},
    )
    assert final_response.status_code == 200
    finished = final_response.json()
    assert finished["run_status"] == "success"
    assert finished["current_stage_key"] is None
    research_stage = next(stage for stage in finished["pipeline_stages"] if stage["stage_key"] == "research_month_rebuild")
    final_stage = next(stage for stage in finished["pipeline_stages"] if stage["stage_key"] == "final_validation")
    assert research_stage["stage_status"] == "passed"
    assert research_stage["metrics"]["written_rows"] == 700
    assert final_stage["stage_status"] == "passed"
    assert final_stage["metrics"]["source_rows"] == 700

    final_events = client.get(run["events_url"]).json()["items"]
    assert [item["event_type"] for item in final_events][-4:] == [
        "pipeline_continue_confirmed",
        "research_month_rebuild_started",
        "research_month_rebuild_progress",
        "pipeline_completed",
    ]
    assert client.get("/api/lake/sync/runs/current").json()["status"] == "idle"


def test_stk_mins_sync_respects_profile_disabled_for_plan_and_start(monkeypatch, tmp_path: Path) -> None:
    lake_root = tmp_path / "lake"
    lake_root.mkdir()
    _write_calendar(lake_root, dates=["2026-05-08"])
    _write_universe(lake_root)
    _patch_settings(monkeypatch, lake_root)
    client = TestClient(create_app())
    plan_response = client.post(
        "/api/lake/sync/profiles/stk_mins_sync/plan",
        json={
            "start_date": "2026-05-08",
            "end_date": "2026-05-08",
            "dataset_keys": ["stk_mins"],
            "freqs": [30],
            "scope": "all_market",
            "mode": "manual_gate",
        },
    )
    assert plan_response.status_code == 200
    plan = plan_response.json()

    class DisabledCatalog:
        def ensure_enabled(self, profile_key: str) -> None:
            raise sync_center.ProfileDisabledError(f"{profile_key} 当前不可启动。")

    monkeypatch.setattr(sync_center, "SyncProfileCatalog", DisabledCatalog)
    blocked_plan_response = client.post(
        "/api/lake/sync/profiles/stk_mins_sync/plan",
        json={
            "start_date": "2026-05-08",
            "end_date": "2026-05-08",
            "dataset_keys": ["stk_mins"],
            "freqs": [30],
            "scope": "all_market",
            "mode": "manual_gate",
        },
    )
    assert blocked_plan_response.status_code == 400
    assert blocked_plan_response.json()["detail"]["code"] == "PROFILE_DISABLED"

    blocked_run_response = client.post(
        "/api/lake/sync/runs",
        json={"plan_token": plan["plan_token"], "confirmed_backup_required": True, "confirmed_no_sql": True},
    )
    assert blocked_run_response.status_code == 400
    assert blocked_run_response.json()["detail"]["code"] == "PROFILE_DISABLED"
    assert client.get("/api/lake/sync/lock").json()["status"] == "idle"


def test_stk_mins_sync_continue_and_abort_only_change_pipeline_state(monkeypatch, tmp_path: Path) -> None:
    lake_root = tmp_path / "lake"
    lake_root.mkdir()
    _write_calendar(lake_root, dates=["2026-05-08"])
    _write_universe(lake_root)
    _patch_settings(monkeypatch, lake_root)
    _run_background_inline(monkeypatch)
    _mock_stk_mins_pipeline_sync(monkeypatch)
    _mock_stk_mins_pipeline_derived(monkeypatch)
    _mock_stk_mins_pipeline_research(monkeypatch)
    client = TestClient(create_app())
    plan = client.post(
        "/api/lake/sync/profiles/stk_mins_sync/plan",
        json={
            "start_date": "2026-05-08",
            "end_date": "2026-05-08",
            "dataset_keys": ["stk_mins"],
            "freqs": [30, 60],
            "scope": "all_market",
            "mode": "manual_gate",
        },
    ).json()
    run = client.post(
        "/api/lake/sync/runs",
        json={"plan_token": plan["plan_token"], "confirmed_backup_required": True, "confirmed_no_sql": True},
    ).json()
    detail = client.get(run["detail_url"]).json()
    for stage in detail["pipeline_stages"]:
        if stage["stage_key"] in {"prewrite_backup", "raw_sync", "clean_next_refresh"}:
            stage["stage_status"] = "passed"
            stage["stage_status_label"] = "已通过"
        if stage["stage_key"] == "clean_next_review":
            stage["stage_status"] = "waiting_confirmation"
            stage["stage_status_label"] = "等待确认"
    waiting_detail = {
        **detail,
        "status": "waiting_confirmation",
        "run_status": "waiting_confirmation",
        "current_stage_key": "clean_next_review",
        "requires_confirmation": True,
        "next_action": {"action": "continue", "label": "继续生成 90/120"},
    }
    LakeJobStateStore(lake_root).write_run(waiting_detail)

    continue_response = client.post(
        f"/api/lake/sync/runs/{run['run_id']}/continue",
        json={"confirm_continue": True, "operator": "tester"},
    )
    assert continue_response.status_code == 200
    continued = continue_response.json()
    assert continued["run_status"] == "waiting_confirmation"
    assert continued["current_stage_key"] == "derived_review"
    assert continued["requires_confirmation"] is True
    clean_review = next(stage for stage in continued["pipeline_stages"] if stage["stage_key"] == "clean_next_review")
    derived_stage = next(stage for stage in continued["pipeline_stages"] if stage["stage_key"] == "derived_90_120_build")
    assert clean_review["stage_status"] == "passed"
    assert clean_review["confirmed_by"] == "tester"
    assert derived_stage["stage_status"] == "passed"

    abort_response = client.post(
        f"/api/lake/sync/runs/{run['run_id']}/abort",
        json={"reason": "测试停止后续写入"},
    )
    assert abort_response.status_code == 200
    aborted = abort_response.json()
    assert aborted["run_status"] == "cancelled"
    assert aborted["requires_confirmation"] is False
    assert client.get("/api/lake/sync/runs/current").json()["status"] == "idle"
    research_stage = next(stage for stage in aborted["pipeline_stages"] if stage["stage_key"] == "research_month_rebuild")
    assert research_stage["stage_status"] == "cancelled"


def test_stk_mins_sync_run_records_kopia_prewrite_backup(monkeypatch, tmp_path: Path) -> None:
    lake_root = tmp_path / "lake"
    existing_partition = lake_root / "raw_tushare" / "stk_mins_by_date" / "freq=30" / "trade_date=2026-05-08"
    existing_partition.mkdir(parents=True)
    (existing_partition / "part-000.parquet").write_text("old", encoding="utf-8")
    _write_calendar(lake_root, dates=["2026-05-08"])
    _write_universe(lake_root)
    _patch_settings(monkeypatch, lake_root)
    _run_background_inline(monkeypatch)
    _mock_stk_mins_pipeline_sync(monkeypatch)
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
                "created_at": "2026-05-15T00:00:00+00:00",
                "snapshot_ids": ["snapshot-stk-mins-001"],
                "snapshots": [{"path": "raw_tushare/stk_mins_by_date", "snapshot_ids": ["snapshot-stk-mins-001"]}],
                "snapshot_paths": backup_plan["snapshot_paths"],
                "backup_paths": backup_plan["backup_paths"],
                "path_missing_before_write": backup_plan["path_missing_before_write"],
            }

    monkeypatch.setattr(sync_center, "KopiaPrewriteBackupService", FakeBackupService)
    client = TestClient(create_app())
    plan = client.post(
        "/api/lake/sync/profiles/stk_mins_sync/plan",
        json={
            "start_date": "2026-05-08",
            "end_date": "2026-05-08",
            "dataset_keys": ["stk_mins"],
            "freqs": [30],
            "scope": "all_market",
            "mode": "manual_gate",
        },
    ).json()

    run_response = client.post(
        "/api/lake/sync/runs",
        json={"plan_token": plan["plan_token"], "confirmed_backup_required": True, "confirmed_no_sql": True},
    )
    assert run_response.status_code == 200
    run = run_response.json()
    assert run["run_status"] == "waiting_confirmation"
    assert run["lock"]["status"] == "idle"
    assert "raw_tushare/stk_mins_by_date" in captured["backup_plan"]["snapshot_paths"]

    detail = client.get(run["detail_url"]).json()
    assert detail["backup"]["snapshot_ids"] == ["snapshot-stk-mins-001"]
    assert detail["current_stage_key"] == "clean_next_review"
    backup_stage = next(stage for stage in detail["pipeline_stages"] if stage["stage_key"] == "prewrite_backup")
    raw_stage = next(stage for stage in detail["pipeline_stages"] if stage["stage_key"] == "raw_sync")
    clean_stage = next(stage for stage in detail["pipeline_stages"] if stage["stage_key"] == "clean_next_refresh")
    assert backup_stage["stage_status"] == "passed"
    assert backup_stage["output_summary"]["snapshot_ids"] == ["snapshot-stk-mins-001"]
    assert backup_stage["metrics"]["snapshot_count"] == 1
    assert raw_stage["stage_status"] == "passed"
    assert clean_stage["stage_status"] == "passed"
    assert clean_stage["display_summary"] == "clean_next/gate 刷新完成：1 个分区已通过。"


def test_stk_mins_sync_run_stops_when_kopia_backup_fails(monkeypatch, tmp_path: Path) -> None:
    lake_root = tmp_path / "lake"
    lake_root.mkdir()
    _write_calendar(lake_root, dates=["2026-05-08"])
    _write_universe(lake_root)
    _patch_settings(monkeypatch, lake_root)

    class FailingBackupService:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def create_prewrite_backup(self, *, run_id: str, profile_key: str, backup_plan: dict[str, Any]) -> dict[str, Any]:
            raise sync_center.KopiaPrewriteBackupError("kopia repository is not connected")

    monkeypatch.setattr(sync_center, "KopiaPrewriteBackupService", FailingBackupService)
    client = TestClient(create_app())
    plan = client.post(
        "/api/lake/sync/profiles/stk_mins_sync/plan",
        json={
            "start_date": "2026-05-08",
            "end_date": "2026-05-08",
            "dataset_keys": ["stk_mins"],
            "freqs": [30],
            "scope": "all_market",
            "mode": "manual_gate",
        },
    ).json()

    run_response = client.post(
        "/api/lake/sync/runs",
        json={"plan_token": plan["plan_token"], "confirmed_backup_required": True, "confirmed_no_sql": True},
    )
    assert run_response.status_code == 503
    detail = run_response.json()["detail"]
    assert detail["code"] == "KOPIA_BACKUP_FAILED"
    assert client.get("/api/lake/sync/lock").json()["status"] == "idle"

    run_detail = client.get(f"/api/lake/sync/runs/{detail['context']['run_id']}").json()
    assert run_detail["run_status"] == "backup_failed"
    assert run_detail["errors"][0]["code"] == "KOPIA_BACKUP_FAILED"
    backup_stage = next(stage for stage in run_detail["pipeline_stages"] if stage["stage_key"] == "prewrite_backup")
    assert backup_stage["stage_status"] == "failed"


def test_sync_center_plan_aggregates_snapshot_paths(monkeypatch, tmp_path: Path) -> None:
    lake_root = tmp_path / "lake"
    (lake_root / "raw_tushare" / "daily" / "trade_date=2026-05-13").mkdir(parents=True)
    (lake_root / "raw_tushare" / "daily" / "trade_date=2026-05-14").mkdir(parents=True)
    _write_calendar(lake_root, dates=["2026-05-13", "2026-05-14"])
    _patch_settings(monkeypatch, lake_root)
    client = TestClient(create_app())

    plan_response = client.post(
        "/api/lake/sync/profiles/prod_db_manual_backfill/plan",
        json={"start_date": "2026-05-13", "end_date": "2026-05-14", "dataset_keys": ["daily"]},
    )

    assert plan_response.status_code == 200
    plan = plan_response.json()
    assert plan["backup_plan"]["backup_paths"] == [
        "raw_tushare/daily/trade_date=2026-05-13",
        "raw_tushare/daily/trade_date=2026-05-14",
    ]
    assert plan["backup_plan"]["snapshot_paths"] == ["raw_tushare/daily"]
    assert plan["backup_plan"]["snapshot_strategy"] == "prewrite_dataset_root_scope"
    assert plan["summary"]["backup_path_count"] == 2
    assert plan["summary"]["snapshot_path_count"] == 1


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
                "snapshot_paths": backup_plan["snapshot_paths"],
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
                "snapshot_paths": backup_plan["snapshot_paths"],
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


def _patch_settings(monkeypatch, lake_root: Path, *, prod_raw_db_url: str | None = None) -> None:
    monkeypatch.setattr(
        sync_center,
        "load_settings",
        lambda: LakeConsoleSettings(
            lake_root=lake_root,
            tushare_token=None,
            prod_raw_db_url=prod_raw_db_url,
        ),
    )


def _run_background_inline(monkeypatch) -> None:
    def run_inline(target, **kwargs: Any) -> None:
        target(**kwargs)

    monkeypatch.setattr(sync_center, "_start_background_task", run_inline)


def _mock_stk_mins_pipeline_sync(monkeypatch) -> None:
    class FakeTushareClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

    class FakeStkMinsSyncService:
        def __init__(self, *, lake_root: Path, client: Any, progress) -> None:  # type: ignore[no-untyped-def]
            self.progress = progress

        def sync_range(self, *, start_date, end_date, freqs, all_market: bool, part_rows: int = 500_000):  # type: ignore[no-untyped-def]
            assert all_market is True
            self.progress("[stk_mins_range] fake raw sync completed")
            affected_partitions = [
                {
                    "dataset_key": "stk_mins",
                    "source_key": "tushare",
                    "layer": "raw_tushare",
                    "partition_grain": "trade_date",
                    "partition_values": {"freq": str(freqs[0]), "trade_date": start_date.isoformat()},
                    "partition_path": f"raw_tushare/stk_mins_by_date/freq={freqs[0]}/trade_date={start_date.isoformat()}",
                    "source_run_id": "fake-stk-mins-range",
                    "write_revision": f"fake-stk-mins-range:raw_tushare:freq={freqs[0]}:trade_date={start_date.isoformat()}",
                    "rows_written": 100,
                    "bytes_written": 1024,
                }
            ]
            return {
                "dataset_key": "stk_mins",
                "api_name": "stk_mins",
                "run_id": "fake-stk-mins-range",
                "mode": "range_all_market",
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "trade_dates": [start_date.isoformat(), end_date.isoformat()],
                "trade_date_count": 2 if start_date != end_date else 1,
                "freqs": freqs,
                "fetched_rows": 100,
                "written_rows": 100,
                "affected_partitions": affected_partitions,
                "clean_next_refresh": {
                    "status": "passed",
                    "partitions": len(affected_partitions),
                    "partition_results": [
                        {
                            "freq": freqs[0],
                            "trade_date": start_date.isoformat(),
                            "status": "passed",
                            "raw_rows": 100,
                            "clean_rows": 100,
                            "issue_count": 0,
                        }
                    ],
                    "gate": {"updated_partitions": len(affected_partitions), "written_rows": len(affected_partitions)},
                },
                "elapsed_seconds": 0.1,
            }

    monkeypatch.setattr(sync_center, "TushareLakeClient", FakeTushareClient)
    monkeypatch.setattr(sync_center, "TushareStkMinsSyncService", FakeStkMinsSyncService)


def _mock_stk_mins_pipeline_derived(monkeypatch) -> None:
    class FakeStkMinsDerivedService:
        def __init__(self, *, lake_root: Path, progress) -> None:  # type: ignore[no-untyped-def]
            self.progress = progress

        def derive_range(self, *, start_date, end_date, targets):  # type: ignore[no-untyped-def]
            self.progress("[derive_stk_mins_range] fake derived completed")
            return {
                "dataset_key": "stk_mins",
                "operation": "derive_stk_mins_range",
                "run_id": "fake-derived-range",
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "trade_dates": [start_date.isoformat(), end_date.isoformat()],
                "trade_date_count": 2 if start_date != end_date else 1,
                "targets": targets,
                "source_rows": 200,
                "written_rows": 80,
                "day_summaries": [],
                "elapsed_seconds": 0.2,
            }

    monkeypatch.setattr(sync_center, "StkMinsDerivedService", FakeStkMinsDerivedService)


def _mock_stk_mins_pipeline_research(monkeypatch) -> None:
    class FakeStkMinsResearchService:
        def __init__(self, *, lake_root: Path, bucket_count: int, progress) -> None:  # type: ignore[no-untyped-def]
            self.progress = progress
            self.bucket_count = bucket_count

        def rebuild_range(self, *, freqs, start_month: str, end_month: str):  # type: ignore[no-untyped-def]
            self.progress("[research_stk_mins_range] fake research completed")
            return {
                "dataset_key": "stk_mins",
                "operation": "research_stk_mins_range",
                "run_id": "fake-research-range",
                "start_month": start_month,
                "end_month": end_month,
                "trade_months": [start_month],
                "freqs": freqs,
                "units_total": len(freqs),
                "source_rows": 700,
                "written_rows": 700,
                "unit_summaries": [],
                "elapsed_seconds": 0.3,
            }

    monkeypatch.setattr(sync_center, "StkMinsResearchService", FakeStkMinsResearchService)


def _write_calendar(lake_root: Path, *, dates: list[str] | None = None) -> None:
    write_rows_to_parquet(
        [{"cal_date": item, "is_open": True} for item in (dates or ["2026-05-14"])],
        lake_root / "manifest" / "trading_calendar" / "tushare_trade_cal.parquet",
    )


def _write_universe(lake_root: Path) -> None:
    write_rows_to_parquet(
        [
            {"ts_code": "000001.SZ", "list_status": "L", "list_date": "19910403", "delist_date": None},
            {"ts_code": "000002.SZ", "list_status": "L", "list_date": "19910129", "delist_date": None},
        ],
        lake_root / "manifest" / "security_universe" / "tushare_stock_basic.parquet",
    )
