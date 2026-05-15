from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from threading import Thread
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
    SyncRunAbortRequest,
    SyncRunContinueRequest,
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
from lake_console.backend.app.services.stk_mins_pipeline_planner import STK_MINS_PIPELINE_PROFILE_KEY, StkMinsPipelinePlanner
from lake_console.backend.app.services.stk_mins_pipeline_run_state import (
    StkMinsPipelineRunAlreadyFinishedError,
    StkMinsPipelineRunNotWaitingConfirmationError,
    abort_pipeline_run,
    build_initial_pipeline_run,
    complete_derived_90_120_stage,
    complete_prewrite_backup_stage,
    complete_raw_and_clean_next_stages,
    complete_research_month_and_final_validation,
    continue_pipeline_run,
    fail_pipeline_stage,
    fail_prewrite_backup_stage,
    normalize_run_detail,
    start_derived_90_120_stage,
    start_prewrite_backup_stage,
    start_raw_sync_stage,
    start_research_month_rebuild_stage,
)
from lake_console.backend.app.services.stk_mins_derived_service import StkMinsDerivedService
from lake_console.backend.app.services.stk_mins_research_service import StkMinsResearchService
from lake_console.backend.app.services.sync_profile_runner import SyncProfileRunner, SyncProfileRunnerError
from lake_console.backend.app.services.sync_recommendation_service import SyncRecommendationService
from lake_console.backend.app.services.sync_center_profiles import ProfileDisabledError, SyncProfileCatalog, SyncProfilePlanner
from lake_console.backend.app.services.tushare_client import TushareLakeClient
from lake_console.backend.app.services.tushare_stk_mins_sync_service import StkMinsProgressEvent, TushareStkMinsSyncService
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
    completed_payload: dict[str, Any] | None = None
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
    if profile_key != STK_MINS_PIPELINE_PROFILE_KEY and (request.freqs is not None or request.scope is not None or request.mode is not None):
        raise _api_error(
            status_code=400,
            code="PROFILE_PARAMETER_NOT_ALLOWED",
            message="freqs、scope、mode 只允许用于 stk_mins_sync。",
        )

    if profile_key == STK_MINS_PIPELINE_PROFILE_KEY:
        try:
            if target_date is not None:
                raise ValueError("stk_mins_sync 计划必须使用 start_date/end_date，不支持 target_date。")
            plan_payload = StkMinsPipelinePlanner(lake_root=settings.lake_root).build_plan(
                dataset_keys=request.dataset_keys,
                start_date=start_date,
                end_date=end_date,
                freqs=request.freqs,
                scope=request.scope,
                mode=request.mode,
            )
        except ValueError as exc:
            raise _api_error(status_code=400, code="INVALID_STK_MINS_PIPELINE_PLAN", message=str(exc)) from exc
    else:
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
    profile_key = str(plan["profile_key"])
    if profile_key == STK_MINS_PIPELINE_PROFILE_KEY:
        return _start_stk_mins_pipeline_state_run(
            settings=settings,
            store=store,
            lock_service=lock_service,
            plan=plan,
            plan_token=request.plan_token,
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

    run_id = new_run_id(profile_key)
    started_at = _utc_now_iso()
    run_payload = {
        "run_id": run_id,
        "profile_key": profile_key,
        "plan_token": request.plan_token,
        "status": "planned",
        "run_status": "planned",
        "started_at": started_at,
        "finished_at": None,
        "backup": None,
        "pipeline_stages": [],
        "current_stage_key": None,
        "requires_confirmation": False,
        "next_action": None,
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
        store.write_run({**run_payload, "status": "lock_acquired", "run_status": "lock_acquired"})
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
                "metrics": {
                    "snapshot_count": len(backup.get("snapshot_ids") or []),
                    "snapshot_path_count": len(backup.get("snapshot_paths") or []),
                    "backup_path_count": len(backup.get("backup_paths") or []),
                    "path_missing_before_write_count": len(backup.get("path_missing_before_write") or []),
                },
            },
        )
        store.write_run({**run_payload, "status": "running", "run_status": "running", "backup": backup})
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
            "run_status": "success",
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
            "run_status": "backup_failed",
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
            "run_status": "failed",
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
            "run_status": "failed",
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
        run_status="success",
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
    return SyncRunDetailResponse(**normalize_run_detail(run))


@router.get("/runs/{run_id}/events", response_model=SyncRunEventListResponse)
def list_run_events(
    run_id: str,
    cursor: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
) -> SyncRunEventListResponse:
    if _state_store().read_run(run_id) is None:
        raise _api_error(status_code=404, code="RUN_NOT_FOUND", message=f"未找到 run：{run_id}")
    return SyncRunEventListResponse(**_state_store().list_events(run_id, cursor=cursor, limit=limit))


@router.post("/runs/{run_id}/continue", response_model=SyncRunDetailResponse)
def continue_run(run_id: str, request: SyncRunContinueRequest) -> SyncRunDetailResponse:
    if not request.confirm_continue:
        raise _api_error(status_code=400, code="CONTINUE_CONFIRMATION_REQUIRED", message="继续前必须显式确认。")
    settings = _settings()
    store = LakeJobStateStore(settings.lake_root)
    lock_service = LakeJobLockService(store)
    run = _load_stk_mins_pipeline_run(store=store, run_id=run_id)
    current_stage_key = str(run.get("current_stage_key") or "")
    if current_stage_key not in {"clean_next_review", "derived_review"}:
        raise _api_error(
            status_code=409,
            code="STK_MINS_PIPELINE_STAGE_NOT_IMPLEMENTED",
            message="当前只支持从 clean_next_review 或 derived_review 继续执行 stk_mins_sync 后续阶段。",
            context={"current_stage_key": current_stage_key},
        )
    try:
        next_run = continue_pipeline_run(run=run, operator=request.operator)
    except StkMinsPipelineRunAlreadyFinishedError as exc:
        raise _api_error(status_code=409, code="RUN_ALREADY_FINISHED", message=str(exc)) from exc
    except StkMinsPipelineRunNotWaitingConfirmationError as exc:
        raise _api_error(status_code=409, code="RUN_NOT_WAITING_CONFIRMATION", message=str(exc)) from exc

    next_stage_key = str(next_run.get("current_stage_key") or "")
    if next_stage_key == "derived_90_120_build":
        parameters = _stk_mins_pipeline_parameters(run=run, store=store)
        derived_freqs = [int(item) for item in parameters.get("derived_freqs") or []]
        if not derived_freqs:
            raise _api_error(
                status_code=409,
                code="STK_MINS_DERIVED_TARGETS_EMPTY",
                message="本轮计划没有 90/120 派生目标，不能执行 derived 阶段。",
                context={"current_stage_key": current_stage_key},
            )
        return _start_stk_mins_derived_90_120_run(
            settings=settings,
            store=store,
            lock_service=lock_service,
            run_id=run_id,
            current_stage_key=current_stage_key,
            next_run=next_run,
            parameters=parameters,
            derived_freqs=derived_freqs,
        )

    if next_stage_key == "research_month_rebuild":
        parameters = _stk_mins_pipeline_parameters(run=run, store=store)
        research_freqs = [int(item) for item in parameters.get("research_freqs") or []]
        affected_months = [str(item) for item in parameters.get("affected_months") or []]
        if not research_freqs or not affected_months:
            raise _api_error(
                status_code=409,
                code="STK_MINS_RESEARCH_SCOPE_EMPTY",
                message="本轮计划缺少 research by month 的频率或月份范围，不能执行 research 阶段。",
                context={"research_freqs": research_freqs, "affected_months": affected_months},
            )
        return _start_stk_mins_research_month_run(
            settings=settings,
            store=store,
            lock_service=lock_service,
            run_id=run_id,
            current_stage_key=current_stage_key,
            next_run=next_run,
            parameters=parameters,
            research_freqs=research_freqs,
            affected_months=affected_months,
        )

    raise _api_error(
        status_code=409,
        code="STK_MINS_PIPELINE_NEXT_STAGE_UNAVAILABLE",
        message="确认后没有可执行的 stk_mins_sync 下一阶段，本轮不会继续推进。",
        context={"next_stage_key": next_stage_key},
    )


def _start_stk_mins_derived_90_120_run(
    *,
    settings: Any,
    store: LakeJobStateStore,
    lock_service: LakeJobLockService,
    run_id: str,
    current_stage_key: str,
    next_run: dict[str, Any],
    parameters: dict[str, Any],
    derived_freqs: list[int],
) -> SyncRunDetailResponse:
    try:
        lock_service.acquire(run_id=run_id, profile_key=STK_MINS_PIPELINE_PROFILE_KEY)
    except LakeJobLockBusyError as exc:
        raise _api_error(
            status_code=409,
            code="LOCK_BUSY",
            message="已有 Lake 写入任务运行或 stale，不能继续执行 derived 90/120。",
            context={"lock": exc.lock_payload},
        ) from exc

    try:
        derived_running = start_derived_90_120_stage(run=next_run)
        store.write_run(derived_running)
        store.append_event(
            run_id,
            {
                "event_type": "pipeline_continue_confirmed",
                "stage_key": current_stage_key,
                "message": next_run["progress"]["summary"],
                "metrics": {"current_stage_key": derived_running.get("current_stage_key")},
            },
        )
        store.append_event(
            run_id,
            {
                "event_type": "derived_90_120_started",
                "stage_key": "derived_90_120_build",
                "message": derived_running["progress"]["summary"],
                "metrics": {
                    "derived_freqs": derived_freqs,
                    "start_date": parameters.get("start_date"),
                    "end_date": parameters.get("end_date"),
                },
            },
        )
        store.write_current(
            _current_payload(
                run_id=run_id,
                profile_key=STK_MINS_PIPELINE_PROFILE_KEY,
                status=derived_running["run_status"],
                summary=derived_running["progress"]["summary"],
                current_stage_key=derived_running.get("current_stage_key"),
                requires_confirmation=bool(derived_running.get("requires_confirmation")),
                next_action=derived_running.get("next_action"),
            )
        )
        _start_background_task(
            _run_stk_mins_derived_90_120_pipeline,
            settings=settings,
            run_id=run_id,
            parameters=parameters,
        )
    except Exception:
        try:
            lock_service.release(run_id=run_id)
        except LakeJobStateError:
            pass
        raise

    latest_payload = normalize_run_detail(store.read_run(run_id) or derived_running)
    return SyncRunDetailResponse(**latest_payload)


def _start_stk_mins_research_month_run(
    *,
    settings: Any,
    store: LakeJobStateStore,
    lock_service: LakeJobLockService,
    run_id: str,
    current_stage_key: str,
    next_run: dict[str, Any],
    parameters: dict[str, Any],
    research_freqs: list[int],
    affected_months: list[str],
) -> SyncRunDetailResponse:
    try:
        lock_service.acquire(run_id=run_id, profile_key=STK_MINS_PIPELINE_PROFILE_KEY)
    except LakeJobLockBusyError as exc:
        raise _api_error(
            status_code=409,
            code="LOCK_BUSY",
            message="已有 Lake 写入任务运行或 stale，不能继续执行 research by month。",
            context={"lock": exc.lock_payload},
        ) from exc

    try:
        research_running = start_research_month_rebuild_stage(run=next_run)
        store.write_run(research_running)
        store.append_event(
            run_id,
            {
                "event_type": "pipeline_continue_confirmed",
                "stage_key": current_stage_key,
                "message": next_run["progress"]["summary"],
                "metrics": {"current_stage_key": research_running.get("current_stage_key")},
            },
        )
        store.append_event(
            run_id,
            {
                "event_type": "research_month_rebuild_started",
                "stage_key": "research_month_rebuild",
                "message": research_running["progress"]["summary"],
                "metrics": {
                    "research_freqs": research_freqs,
                    "affected_months": affected_months,
                    "bucket_count": settings.bucket_count,
                },
            },
        )
        store.write_current(
            _current_payload(
                run_id=run_id,
                profile_key=STK_MINS_PIPELINE_PROFILE_KEY,
                status=research_running["run_status"],
                summary=research_running["progress"]["summary"],
                current_stage_key=research_running.get("current_stage_key"),
                requires_confirmation=bool(research_running.get("requires_confirmation")),
                next_action=research_running.get("next_action"),
            )
        )
        _start_background_task(
            _run_stk_mins_research_month_pipeline,
            settings=settings,
            run_id=run_id,
            parameters=parameters,
        )
    except Exception:
        try:
            lock_service.release(run_id=run_id)
        except LakeJobStateError:
            pass
        raise

    latest_payload = normalize_run_detail(store.read_run(run_id) or research_running)
    return SyncRunDetailResponse(**latest_payload)


@router.post("/runs/{run_id}/abort", response_model=SyncRunDetailResponse)
def abort_run(run_id: str, request: SyncRunAbortRequest) -> SyncRunDetailResponse:
    store = _state_store()
    run = _load_stk_mins_pipeline_run(store=store, run_id=run_id)
    try:
        next_run = abort_pipeline_run(run=run, reason=request.reason)
    except StkMinsPipelineRunAlreadyFinishedError as exc:
        raise _api_error(status_code=409, code="RUN_ALREADY_FINISHED", message=str(exc)) from exc
    store.write_run(next_run)
    store.append_event(
        run_id,
        {
            "event_type": "pipeline_aborted",
            "level": "warning",
            "stage_key": run.get("current_stage_key"),
            "message": request.reason,
        },
    )
    store.write_current(_idle_current_payload(summary=f"stk_mins_sync 已停止：{request.reason}"))
    return SyncRunDetailResponse(**normalize_run_detail(next_run))


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


def _start_stk_mins_pipeline_state_run(
    *,
    settings: Any,
    store: LakeJobStateStore,
    lock_service: LakeJobLockService,
    plan: dict[str, Any],
    plan_token: str,
) -> SyncRunResponse:
    run_id = new_run_id(STK_MINS_PIPELINE_PROFILE_KEY)
    run_payload = build_initial_pipeline_run(
        plan=plan,
        plan_token=plan_token,
        run_id=run_id,
        started_at=_utc_now_iso(),
    )
    try:
        lock_service.acquire(run_id=run_id, profile_key=STK_MINS_PIPELINE_PROFILE_KEY)
    except LakeJobLockBusyError as exc:
        raise _api_error(
            status_code=409,
            code="LOCK_BUSY",
            message="已有 Lake 写入任务运行或 stale，不能启动新任务。",
            context={"lock": exc.lock_payload},
        ) from exc

    try:
        store.write_run(run_payload)
        store.write_current(
            _current_payload(
                run_id=run_id,
                profile_key=STK_MINS_PIPELINE_PROFILE_KEY,
                status=run_payload["run_status"],
                summary=run_payload["progress"]["summary"],
                current_stage_key=run_payload.get("current_stage_key"),
                requires_confirmation=bool(run_payload.get("requires_confirmation")),
                next_action=run_payload.get("next_action"),
            )
        )
        store.append_event(
            run_id,
            {
                "event_type": "pipeline_run_created",
                "stage_key": run_payload.get("current_stage_key"),
                "message": run_payload["progress"]["summary"],
                "metrics": {
                    "stage_count": len(run_payload.get("pipeline_stages") or []),
                    "state_only": True,
                },
            },
        )
        backup_running_payload = start_prewrite_backup_stage(run=run_payload)
        store.write_run(backup_running_payload)
        store.write_current(
            _current_payload(
                run_id=run_id,
                profile_key=STK_MINS_PIPELINE_PROFILE_KEY,
                status=backup_running_payload["run_status"],
                summary=backup_running_payload["progress"]["summary"],
                current_stage_key=backup_running_payload.get("current_stage_key"),
                requires_confirmation=bool(backup_running_payload.get("requires_confirmation")),
                next_action=backup_running_payload.get("next_action"),
            )
        )
        store.append_event(
            run_id,
            {
                "event_type": "backup_started",
                "stage_key": "prewrite_backup",
                "message": "开始创建 Kopia prewrite snapshot。",
            },
        )
        backup_service = KopiaPrewriteBackupService(
            lake_root=settings.lake_root,
            kopia_bin=settings.kopia_bin,
            kopia_config_path=settings.kopia_config_path,
            kopia_password=settings.kopia_password,
        )
        backup = backup_service.create_prewrite_backup(
            run_id=run_id,
            profile_key=STK_MINS_PIPELINE_PROFILE_KEY,
            backup_plan=plan.get("backup_plan") or {},
        )
        store.write_backup_record(run_id, backup)
        completed_payload = complete_prewrite_backup_stage(run=backup_running_payload, backup=backup)
        store.write_run(completed_payload)
        store.append_event(
            run_id,
            {
                "event_type": "backup_completed",
                "stage_key": "prewrite_backup",
                "message": completed_payload["progress"]["summary"],
                "metrics": {
                    "snapshot_count": len(backup.get("snapshot_ids") or []),
                    "snapshot_path_count": len(backup.get("snapshot_paths") or []),
                    "backup_path_count": len(backup.get("backup_paths") or []),
                    "path_missing_before_write_count": len(backup.get("path_missing_before_write") or []),
                },
            },
        )
        raw_running_payload = start_raw_sync_stage(run=completed_payload)
        store.write_run(raw_running_payload)
        store.write_current(
            _current_payload(
                run_id=run_id,
                profile_key=STK_MINS_PIPELINE_PROFILE_KEY,
                status=raw_running_payload["run_status"],
                summary=raw_running_payload["progress"]["summary"],
                current_stage_key=raw_running_payload.get("current_stage_key"),
                requires_confirmation=bool(raw_running_payload.get("requires_confirmation")),
                next_action=raw_running_payload.get("next_action"),
            )
        )
        store.append_event(
            run_id,
            {
                "event_type": "raw_sync_started",
                "stage_key": "raw_sync",
                "message": raw_running_payload["progress"]["summary"],
            },
        )
        _start_background_task(
            _run_stk_mins_raw_clean_next_pipeline,
            settings=settings,
            run_id=run_id,
            plan=plan,
        )
    except KopiaPrewriteBackupError as exc:
        error = {"code": "KOPIA_BACKUP_FAILED", "message": str(exc)}
        failed_payload = fail_prewrite_backup_stage(run=run_payload, error=error)
        store.write_run(failed_payload)
        store.append_event(
            run_id,
            {
                "event_type": "backup_failed",
                "level": "error",
                "stage_key": "prewrite_backup",
                "message": str(exc),
                "error": error,
            },
        )
        store.write_current(_idle_current_payload(summary=failed_payload["progress"]["summary"]))
        try:
            lock_service.release(run_id=run_id)
        except LakeJobStateError:
            pass
        raise _api_error(
            status_code=503,
            code="KOPIA_BACKUP_FAILED",
            message="Kopia prewrite snapshot 创建失败，未执行任何写入。",
            context={"run_id": run_id, "error": str(exc)},
        ) from exc
        try:
            lock_service.release(run_id=run_id)
        except LakeJobStateError:
            pass
    if completed_payload is None:
        raise _api_error(
            status_code=500,
            code="STK_MINS_PIPELINE_BACKUP_STATE_MISSING",
            message="stk_mins_sync 写前备份状态缺失。",
            context={"run_id": run_id},
        )
    latest_payload = normalize_run_detail(store.read_run(run_id) or completed_payload)
    return SyncRunResponse(
        run_id=run_id,
        profile_key=STK_MINS_PIPELINE_PROFILE_KEY,
        status=latest_payload["status"],
        run_status=latest_payload["run_status"],
        lock=LakeJobLockService(store).get_lock(),
        detail_url=f"/api/lake/sync/runs/{run_id}",
        events_url=f"/api/lake/sync/runs/{run_id}/events",
    )


def _run_stk_mins_raw_clean_next_pipeline(*, settings: Any, run_id: str, plan: dict[str, Any]) -> None:
    store = LakeJobStateStore(settings.lake_root)
    lock_service = LakeJobLockService(store)
    try:
        current_run = normalize_run_detail(store.read_run(run_id) or {})
        parameters = dict(plan.get("normalized_parameters") or {})
        service = TushareStkMinsSyncService(
            lake_root=settings.lake_root,
            client=TushareLakeClient(
                settings.tushare_token,
                request_limit_per_minute=settings.tushare_request_limit_per_minute,
            ),
            progress=lambda event: store.append_event(run_id, _stk_mins_progress_event(event)),
        )
        summary = service.sync_range(
            start_date=date.fromisoformat(str(parameters["start_date"])),
            end_date=date.fromisoformat(str(parameters["end_date"])),
            freqs=[int(item) for item in parameters.get("freqs") or []],
            all_market=True,
        )
        latest_run = normalize_run_detail(store.read_run(run_id) or current_run)
        next_run = complete_raw_and_clean_next_stages(run=latest_run, summary=summary)
        store.write_run(next_run)
        if next_run["run_status"] == "waiting_confirmation":
            store.write_current(
                _current_payload(
                    run_id=run_id,
                    profile_key=STK_MINS_PIPELINE_PROFILE_KEY,
                    status=next_run["run_status"],
                    summary=next_run["progress"]["summary"],
                    current_stage_key=next_run.get("current_stage_key"),
                    requires_confirmation=bool(next_run.get("requires_confirmation")),
                    next_action=next_run.get("next_action"),
                )
            )
            store.append_event(
                run_id,
                {
                    "event_type": "clean_next_review_waiting",
                    "stage_key": "clean_next_review",
                    "message": next_run["progress"]["summary"],
                    "metrics": {
                        "fetched_rows": summary.get("fetched_rows"),
                        "written_rows": summary.get("written_rows"),
                        "affected_partition_count": len(summary.get("affected_partitions") or []),
                    },
                },
            )
        else:
            store.write_current(_idle_current_payload(summary=next_run["progress"]["summary"]))
            store.append_event(
                run_id,
                {
                    "event_type": "raw_clean_next_failed",
                    "level": "error",
                    "stage_key": next_run.get("current_stage_key"),
                    "message": next_run["progress"]["summary"],
                    "error": (next_run.get("errors") or [{}])[0],
                },
            )
    except Exception as exc:
        latest_run = normalize_run_detail(store.read_run(run_id) or {"run_id": run_id, "profile_key": STK_MINS_PIPELINE_PROFILE_KEY})
        error = {"code": "STK_MINS_RAW_CLEAN_NEXT_FAILED", "message": str(exc)}
        failed_run = fail_pipeline_stage(run=latest_run, stage_key="raw_sync", error=error)
        store.write_run(failed_run)
        store.append_event(
            run_id,
            {
                "event_type": "raw_clean_next_failed",
                "level": "error",
                "stage_key": "raw_sync",
                "message": str(exc),
                "error": error,
            },
        )
        store.write_current(_idle_current_payload(summary=failed_run["progress"]["summary"]))
    finally:
        try:
            lock_service.release(run_id=run_id)
        except LakeJobStateError:
            pass


def _run_stk_mins_derived_90_120_pipeline(*, settings: Any, run_id: str, parameters: dict[str, Any]) -> None:
    store = LakeJobStateStore(settings.lake_root)
    lock_service = LakeJobLockService(store)
    try:
        current_run = normalize_run_detail(store.read_run(run_id) or {})
        service = StkMinsDerivedService(
            lake_root=settings.lake_root,
            progress=lambda event: store.append_event(run_id, _stk_mins_derived_progress_event(event)),
        )
        summary = service.derive_range(
            start_date=date.fromisoformat(str(parameters["start_date"])),
            end_date=date.fromisoformat(str(parameters["end_date"])),
            targets=[int(item) for item in parameters.get("derived_freqs") or []],
        )
        latest_run = normalize_run_detail(store.read_run(run_id) or current_run)
        next_run = complete_derived_90_120_stage(run=latest_run, summary=summary)
        store.write_run(next_run)
        store.write_current(
            _current_payload(
                run_id=run_id,
                profile_key=STK_MINS_PIPELINE_PROFILE_KEY,
                status=next_run["run_status"],
                summary=next_run["progress"]["summary"],
                current_stage_key=next_run.get("current_stage_key"),
                requires_confirmation=bool(next_run.get("requires_confirmation")),
                next_action=next_run.get("next_action"),
            )
        )
        store.append_event(
            run_id,
            {
                "event_type": "derived_review_waiting",
                "stage_key": "derived_review",
                "message": next_run["progress"]["summary"],
                "metrics": {
                    "source_rows": summary.get("source_rows"),
                    "written_rows": summary.get("written_rows"),
                    "trade_date_count": summary.get("trade_date_count"),
                    "targets": summary.get("targets") or [],
                },
            },
        )
    except Exception as exc:
        latest_run = normalize_run_detail(store.read_run(run_id) or {"run_id": run_id, "profile_key": STK_MINS_PIPELINE_PROFILE_KEY})
        error = {"code": "STK_MINS_DERIVED_90_120_FAILED", "message": str(exc)}
        failed_run = fail_pipeline_stage(run=latest_run, stage_key="derived_90_120_build", error=error)
        store.write_run(failed_run)
        store.append_event(
            run_id,
            {
                "event_type": "derived_90_120_failed",
                "level": "error",
                "stage_key": "derived_90_120_build",
                "message": str(exc),
                "error": error,
            },
        )
        store.write_current(_idle_current_payload(summary=failed_run["progress"]["summary"]))
    finally:
        try:
            lock_service.release(run_id=run_id)
        except LakeJobStateError:
            pass


def _run_stk_mins_research_month_pipeline(*, settings: Any, run_id: str, parameters: dict[str, Any]) -> None:
    store = LakeJobStateStore(settings.lake_root)
    lock_service = LakeJobLockService(store)
    try:
        current_run = normalize_run_detail(store.read_run(run_id) or {})
        affected_months = [str(item) for item in parameters.get("affected_months") or []]
        service = StkMinsResearchService(
            lake_root=settings.lake_root,
            bucket_count=settings.bucket_count,
            progress=lambda event: store.append_event(run_id, _stk_mins_research_progress_event(event)),
        )
        summary = service.rebuild_range(
            freqs=[int(item) for item in parameters.get("research_freqs") or []],
            start_month=affected_months[0],
            end_month=affected_months[-1],
        )
        latest_run = normalize_run_detail(store.read_run(run_id) or current_run)
        next_run = complete_research_month_and_final_validation(run=latest_run, summary=summary)
        store.write_run(next_run)
        if next_run["run_status"] == "success":
            store.write_current(_idle_current_payload(summary=next_run["progress"]["summary"]))
            store.append_event(
                run_id,
                {
                    "event_type": "pipeline_completed",
                    "stage_key": "final_validation",
                    "message": next_run["progress"]["summary"],
                    "metrics": {
                        "source_rows": summary.get("source_rows"),
                        "written_rows": summary.get("written_rows"),
                        "units_total": summary.get("units_total"),
                        "freqs": summary.get("freqs") or [],
                        "trade_months": summary.get("trade_months") or [],
                    },
                },
            )
        else:
            store.write_current(_idle_current_payload(summary=next_run["progress"]["summary"]))
            store.append_event(
                run_id,
                {
                    "event_type": "research_month_rebuild_failed",
                    "level": "error",
                    "stage_key": next_run.get("current_stage_key"),
                    "message": next_run["progress"]["summary"],
                    "error": (next_run.get("errors") or [{}])[0],
                },
            )
    except Exception as exc:
        latest_run = normalize_run_detail(store.read_run(run_id) or {"run_id": run_id, "profile_key": STK_MINS_PIPELINE_PROFILE_KEY})
        error = {"code": "STK_MINS_RESEARCH_MONTH_FAILED", "message": str(exc)}
        failed_run = fail_pipeline_stage(run=latest_run, stage_key="research_month_rebuild", error=error)
        store.write_run(failed_run)
        store.append_event(
            run_id,
            {
                "event_type": "research_month_rebuild_failed",
                "level": "error",
                "stage_key": "research_month_rebuild",
                "message": str(exc),
                "error": error,
            },
        )
        store.write_current(_idle_current_payload(summary=failed_run["progress"]["summary"]))
    finally:
        try:
            lock_service.release(run_id=run_id)
        except LakeJobStateError:
            pass


def _stk_mins_progress_event(event: str | StkMinsProgressEvent) -> dict[str, Any]:
    if isinstance(event, StkMinsProgressEvent):
        return {
            "event_type": "raw_sync_progress",
            "stage_key": "raw_sync",
            "dataset_key": "stk_mins",
            "message": f"freq={event.freq} ts_code={event.ts_code} fetched={event.fetched_rows}",
            "metrics": {
                "units_done": event.units_done,
                "units_total": event.units_total,
                "ts_code": event.ts_code,
                "trade_date": event.trade_date.isoformat() if event.trade_date else None,
                "freq": event.freq,
                "fetched_rows": event.fetched_rows,
                "written_rows": event.written_rows,
                "window_start": event.window_start.isoformat() if event.window_start else None,
                "window_end": event.window_end.isoformat() if event.window_end else None,
                "page": event.page,
                "offset": event.offset,
            },
        }
    return {
        "event_type": "raw_sync_progress",
        "stage_key": "raw_sync",
        "dataset_key": "stk_mins",
        "message": str(event),
    }


def _stk_mins_derived_progress_event(event: str) -> dict[str, Any]:
    return {
        "event_type": "derived_90_120_progress",
        "stage_key": "derived_90_120_build",
        "dataset_key": "stk_mins",
        "message": str(event),
    }


def _stk_mins_research_progress_event(event: str) -> dict[str, Any]:
    return {
        "event_type": "research_month_rebuild_progress",
        "stage_key": "research_month_rebuild",
        "dataset_key": "stk_mins",
        "message": str(event),
    }


def _start_background_task(target, **kwargs: Any) -> None:
    Thread(target=target, kwargs=kwargs, daemon=True).start()


def _stk_mins_pipeline_parameters(*, run: dict[str, Any], store: LakeJobStateStore) -> dict[str, Any]:
    parameters = dict(run.get("normalized_parameters") or {})
    if parameters:
        return parameters
    plan = store.read_plan(str(run.get("plan_token") or ""))
    return dict(plan.get("normalized_parameters") or {})


def _load_stk_mins_pipeline_run(*, store: LakeJobStateStore, run_id: str) -> dict[str, Any]:
    run = store.read_run(run_id)
    if run is None:
        raise _api_error(status_code=404, code="RUN_NOT_FOUND", message=f"未找到 run：{run_id}")
    if str(run.get("profile_key") or "") != STK_MINS_PIPELINE_PROFILE_KEY:
        raise _api_error(
            status_code=400,
            code="RUN_ACTION_PROFILE_NOT_SUPPORTED",
            message="continue/abort 当前只支持 stk_mins_sync 阶段化 run。",
            context={"profile_key": run.get("profile_key")},
        )
    return normalize_run_detail(run)


def _parse_date(value: str | None, *, field_name: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise _api_error(status_code=400, code="INVALID_DATE", message=f"{field_name} 必须是 YYYY-MM-DD：{value}") from exc


def _api_error(*, status_code: int, code: str, message: str, context: dict[str, Any] | None = None) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message, "context": context or {}})


def _current_payload(
    *,
    run_id: str,
    profile_key: str,
    status: str,
    summary: str,
    current_stage_key: str | None = None,
    requires_confirmation: bool = False,
    next_action: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "active_run_id": run_id,
        "profile_key": profile_key,
        "status": status,
        "started_at": _utc_now_iso(),
        "updated_at": _utc_now_iso(),
        "progress_summary": summary,
        "current_dataset_key": None,
        "current_partition": None,
        "current_stage_key": current_stage_key,
        "requires_confirmation": requires_confirmation,
        "next_action": next_action,
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
        "current_stage_key": None,
        "requires_confirmation": False,
        "next_action": None,
    }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
