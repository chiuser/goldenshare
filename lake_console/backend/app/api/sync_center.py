from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from lake_console.backend.app.schemas import (
    SyncCurrentRunResponse,
    SyncLockResponse,
    SyncPlanRequest,
    SyncPlanResponse,
    SyncProfileListResponse,
    SyncRecommendationResponse,
    SyncReleaseStaleLockRequest,
    SyncReleaseStaleLockResponse,
    SyncRunDetailResponse,
    SyncRunEventListResponse,
    SyncRunRequest,
    SyncRunResponse,
)
from lake_console.backend.app.services.kopia_prewrite_backup_service import KopiaPrewriteBackupError, KopiaPrewriteBackupService
from lake_console.backend.app.services.lake_job_state import (
    LakeJobLockBusyError,
    LakeJobLockService,
    LakeJobStateError,
    LakeJobStateStore,
    PlanExpiredError,
    PlanNotFoundError,
    new_plan_token,
    new_run_id,
)
from lake_console.backend.app.services.sync_profile_runner import SyncProfileRunner, SyncProfileRunnerError
from lake_console.backend.app.services.sync_recommendation_service import SyncRecommendationService
from lake_console.backend.app.services.sync_center_profiles import ProfileDisabledError, SyncProfileCatalog, SyncProfilePlanner
from lake_console.backend.app.settings import LakeConsoleConfigError, load_settings


router = APIRouter(prefix="/api/lake/sync", tags=["sync"])


@router.get("/profiles", response_model=SyncProfileListResponse)
def list_profiles() -> SyncProfileListResponse:
    catalog = SyncProfileCatalog()
    return SyncProfileListResponse(items=[profile.to_summary() for profile in catalog.list_profiles()])


@router.get("/lock", response_model=SyncLockResponse)
def get_lock() -> SyncLockResponse:
    store = _state_store()
    return SyncLockResponse(**LakeJobLockService(store).get_lock())


@router.get("/recommendations", response_model=SyncRecommendationResponse)
def get_recommendations(profile_key: str = Query(default="prod_db_daily")) -> SyncRecommendationResponse:
    settings = _settings()
    try:
        payload = SyncRecommendationService(lake_root=settings.lake_root).build(profile_key=profile_key)
    except ValueError as exc:
        raise _api_error(status_code=400, code="UNSUPPORTED_RECOMMENDATION_PROFILE", message=str(exc)) from exc
    return SyncRecommendationResponse(**payload)


@router.post("/profiles/{profile_key}/plan", response_model=SyncPlanResponse)
def create_plan(profile_key: str, request: SyncPlanRequest) -> SyncPlanResponse:
    settings = _settings()
    store = LakeJobStateStore(settings.lake_root)
    planner = SyncProfilePlanner(lake_root=settings.lake_root)
    target_date = _parse_date(request.target_date, field_name="target_date")
    start_date = _parse_date(request.start_date, field_name="start_date")
    end_date = _parse_date(request.end_date, field_name="end_date")
    if (start_date is None) != (end_date is None):
        raise _api_error(
            status_code=400,
            code="INVALID_DATE_RANGE",
            message="start_date 和 end_date 必须同时传入。",
        )
    if start_date and end_date and end_date < start_date:
        raise _api_error(
            status_code=400,
            code="INVALID_DATE_RANGE",
            message="end_date 不能早于 start_date。",
        )

    try:
        plan_payload = planner.build_plan(
            profile_key=profile_key,
            dataset_keys=request.dataset_keys,
            target_date=target_date,
            start_date=start_date,
            end_date=end_date,
        )
    except ProfileDisabledError as exc:
        raise _api_error(status_code=400, code="PROFILE_DISABLED", message=str(exc)) from exc
    except ValueError as exc:
        raise _api_error(status_code=400, code="DATASET_NOT_ALLOWED", message=str(exc)) from exc

    token = new_plan_token()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
    payload = {
        "plan_token": token,
        "plan_token_expires_at": expires_at.isoformat(),
        "profile_key": profile_key,
        "lock": LakeJobLockService(store).get_lock(),
        **plan_payload,
    }
    store.write_plan(payload)
    return SyncPlanResponse(**payload)


@router.post("/runs", response_model=SyncRunResponse)
def start_run(request: SyncRunRequest) -> SyncRunResponse:
    if not request.confirmed_backup_required:
        raise _api_error(
            status_code=400,
            code="BACKUP_CONFIRMATION_REQUIRED",
            message="启动写入任务前必须确认 Kopia prewrite backup。",
        )
    if not request.confirmed_no_sql:
        raise _api_error(
            status_code=400,
            code="NO_SQL_CONFIRMATION_REQUIRED",
            message="Sync Center 不提供 SQL 入口，启动前必须确认本次不是 SQL 任务。",
        )

    settings = _settings()
    store = LakeJobStateStore(settings.lake_root)
    lock_service = LakeJobLockService(store)
    try:
        plan = store.read_plan(request.plan_token)
    except PlanNotFoundError as exc:
        raise _api_error(status_code=404, code="PLAN_NOT_FOUND", message=str(exc)) from exc
    except PlanExpiredError as exc:
        raise _api_error(status_code=400, code="PLAN_EXPIRED", message=str(exc)) from exc

    blockers = list(plan.get("blockers") or [])
    if blockers:
        raise _api_error(
            status_code=409,
            code="PLAN_BLOCKED",
            message="计划仍存在 blockers，不能启动 run。",
            context={"blockers": blockers},
        )
    try:
        SyncProfileRunner.validate_plan(plan=plan)
    except SyncProfileRunnerError as exc:
        raise _api_error(
            status_code=400,
            code="SYNC_PROFILE_RUNNER_UNSUPPORTED_SCOPE",
            message=str(exc),
            context={"profile_key": plan.get("profile_key"), "dataset_plans": plan.get("dataset_plans") or []},
        ) from exc

    profile_key = str(plan["profile_key"])
    run_id = new_run_id(profile_key)
    started_at = _utc_now_iso()
    run_payload = {
        "run_id": run_id,
        "profile_key": profile_key,
        "plan_token": request.plan_token,
        "status": "planned",
        "started_at": started_at,
        "finished_at": None,
        "backup": None,
        "progress": {
            "summary": "任务已创建，等待获取写入锁。",
            "current_dataset_key": None,
            "current_partition": None,
        },
        "dataset_results": [],
        "errors": [],
    }
    try:
        lock = lock_service.acquire(run_id=run_id, profile_key=profile_key)
    except LakeJobLockBusyError as exc:
        raise _api_error(
            status_code=409,
            code="LOCK_BUSY",
            message="已有 Lake 写入任务运行或 stale，不能启动新任务。",
            context={"lock": exc.lock_payload},
        ) from exc

    backup: dict[str, Any] | None = None
    try:
        store.write_run({**run_payload, "status": "lock_acquired"})
        store.write_current(_current_payload(run_id=run_id, profile_key=profile_key, status="backup_running", summary="已拿到写入锁，正在创建 Kopia 预写备份。"))
        store.append_event(run_id, {"event_type": "run_started", "message": "Sync Center run 已启动。"})
        store.append_event(run_id, {"event_type": "lock_acquired", "message": "已获取 Lake 写入锁。"})
        backup_service = KopiaPrewriteBackupService(
            lake_root=settings.lake_root,
            kopia_bin=settings.kopia_bin,
            kopia_config_path=settings.kopia_config_path,
            kopia_password=settings.kopia_password,
        )
        store.append_event(run_id, {"event_type": "backup_started", "message": "开始创建 Kopia prewrite snapshot。"})
        backup = backup_service.create_prewrite_backup(run_id=run_id, profile_key=profile_key, backup_plan=plan.get("backup_plan") or {})
        store.write_backup_record(run_id, backup)
        store.append_event(
            run_id,
            {
                "event_type": "backup_completed",
                "message": "Kopia prewrite snapshot 已完成。",
                "metrics": {"snapshot_count": len(backup.get("snapshot_ids") or [])},
            },
        )
        store.write_run({**run_payload, "status": "running", "backup": backup})
        store.write_current(
            _current_payload(
                run_id=run_id,
                profile_key=profile_key,
                status="running",
                summary="Kopia 预写备份已完成，正在执行 Sync Profile Runner。",
            )
        )
        store.append_event(run_id, {"event_type": "execution_started", "message": "开始执行 Sync Profile Runner。"})
        runner = SyncProfileRunner(
            settings=settings,
            progress=lambda event: store.append_event(run_id, event),
        )
        runner_result = runner.run(plan=plan)
        final_payload = {
            **run_payload,
            "status": "success",
            "finished_at": _utc_now_iso(),
            "backup": backup,
            "progress": runner_result.get("progress") or {},
            "dataset_results": runner_result.get("dataset_results") or [],
            "errors": [],
        }
        store.write_run(final_payload)
        store.append_event(run_id, {"event_type": "run_completed", "message": "Sync Center run 执行完成。"})
        store.write_current(_idle_current_payload(summary="最近一次 Sync Center run 已执行完成。"))
    except KopiaPrewriteBackupError as exc:
        failed = {
            **run_payload,
            "status": "backup_failed",
            "finished_at": _utc_now_iso(),
            "errors": [{"code": "KOPIA_BACKUP_FAILED", "message": str(exc)}],
        }
        store.write_run(failed)
        store.append_event(run_id, {"event_type": "backup_failed", "level": "error", "message": str(exc), "error": {"code": "KOPIA_BACKUP_FAILED", "message": str(exc)}})
        store.write_current(_idle_current_payload(summary="Kopia prewrite backup 失败，未执行任何数据写入。"))
        raise _api_error(
            status_code=503,
            code="KOPIA_BACKUP_FAILED",
            message="Kopia prewrite snapshot 创建失败，未执行任何写入。",
            context={"run_id": run_id, "error": str(exc)},
        ) from exc
    except SyncProfileRunnerError as exc:
        failed = {
            **run_payload,
            "status": "failed",
            "finished_at": _utc_now_iso(),
            "backup": backup,
            "errors": [{"code": "SYNC_PROFILE_RUNNER_FAILED", "message": str(exc)}],
        }
        store.write_run(failed)
        store.append_event(run_id, {"event_type": "run_failed", "level": "error", "message": str(exc), "error": {"code": "SYNC_PROFILE_RUNNER_FAILED", "message": str(exc)}})
        store.write_current(_idle_current_payload(summary="Sync Profile Runner 执行失败。"))
        raise _api_error(
            status_code=500,
            code="SYNC_PROFILE_RUNNER_FAILED",
            message=str(exc),
            context={"run_id": run_id},
        ) from exc
    except Exception as exc:
        failed = {
            **run_payload,
            "status": "failed",
            "finished_at": _utc_now_iso(),
            "backup": backup,
            "errors": [{"code": "SYNC_PROFILE_RUNNER_UNEXPECTED_ERROR", "message": str(exc)}],
        }
        store.write_run(failed)
        store.append_event(run_id, {"event_type": "run_failed", "level": "error", "message": str(exc), "error": {"code": "SYNC_PROFILE_RUNNER_UNEXPECTED_ERROR", "message": str(exc)}})
        store.write_current(_idle_current_payload(summary="Sync Profile Runner 执行异常。"))
        raise _api_error(
            status_code=500,
            code="SYNC_PROFILE_RUNNER_UNEXPECTED_ERROR",
            message=str(exc),
            context={"run_id": run_id},
        ) from exc
    finally:
        try:
            lock_service.release(run_id=run_id)
        except LakeJobStateError:
            pass

    return SyncRunResponse(
        run_id=run_id,
        profile_key=profile_key,
        status="success",
        lock=LakeJobLockService(store).get_lock(),
        detail_url=f"/api/lake/sync/runs/{run_id}",
        events_url=f"/api/lake/sync/runs/{run_id}/events",
    )


@router.get("/runs/current", response_model=SyncCurrentRunResponse)
def get_current_run() -> SyncCurrentRunResponse:
    return SyncCurrentRunResponse(**_state_store().read_current())


@router.get("/runs/{run_id}", response_model=SyncRunDetailResponse)
def get_run(run_id: str) -> SyncRunDetailResponse:
    run = _state_store().read_run(run_id)
    if run is None:
        raise _api_error(status_code=404, code="RUN_NOT_FOUND", message=f"未找到 run：{run_id}")
    return SyncRunDetailResponse(**run)


@router.get("/runs/{run_id}/events", response_model=SyncRunEventListResponse)
def list_run_events(
    run_id: str,
    cursor: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
) -> SyncRunEventListResponse:
    if _state_store().read_run(run_id) is None:
        raise _api_error(status_code=404, code="RUN_NOT_FOUND", message=f"未找到 run：{run_id}")
    return SyncRunEventListResponse(**_state_store().list_events(run_id, cursor=cursor, limit=limit))


@router.post("/lock/release-stale", response_model=SyncReleaseStaleLockResponse)
def release_stale_lock(request: SyncReleaseStaleLockRequest) -> SyncReleaseStaleLockResponse:
    if not request.confirm_stale:
        raise _api_error(status_code=400, code="STALE_CONFIRMATION_REQUIRED", message="释放 stale lock 前必须显式确认。")
    store = _state_store()
    lock_service = LakeJobLockService(store)
    try:
        released = lock_service.release_stale(reason=request.reason)
    except LakeJobStateError as exc:
        raise _api_error(status_code=409, code="LOCK_NOT_STALE", message=str(exc)) from exc
    run_id = released.get("run_id")
    if run_id:
        store.append_event(str(run_id), {"event_type": "stale_lock_released", "level": "warning", "message": request.reason})
    store.write_current(_idle_current_payload(summary="stale lock 已由操作员释放。"))
    return SyncReleaseStaleLockResponse(released=True, released_lock=released)


def _settings():
    try:
        return load_settings()
    except LakeConsoleConfigError as exc:
        raise _api_error(status_code=400, code="LAKE_ROOT_REQUIRED", message=str(exc)) from exc


def _state_store() -> LakeJobStateStore:
    return LakeJobStateStore(_settings().lake_root)


def _parse_date(value: str | None, *, field_name: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise _api_error(status_code=400, code="INVALID_DATE", message=f"{field_name} 必须是 YYYY-MM-DD：{value}") from exc


def _api_error(*, status_code: int, code: str, message: str, context: dict[str, Any] | None = None) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message, "context": context or {}})


def _current_payload(*, run_id: str, profile_key: str, status: str, summary: str) -> dict[str, Any]:
    return {
        "active_run_id": run_id,
        "profile_key": profile_key,
        "status": status,
        "started_at": _utc_now_iso(),
        "updated_at": _utc_now_iso(),
        "progress_summary": summary,
        "current_dataset_key": None,
        "current_partition": None,
    }


def _idle_current_payload(*, summary: str) -> dict[str, Any]:
    return {
        "active_run_id": None,
        "profile_key": None,
        "status": "idle",
        "started_at": None,
        "updated_at": _utc_now_iso(),
        "progress_summary": summary,
        "current_dataset_key": None,
        "current_partition": None,
    }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
