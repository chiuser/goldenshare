from __future__ import annotations

from fastapi import APIRouter, Depends
from src.platform.auth.dependencies import require_admin
from src.platform.auth.domain import AuthenticatedUser
from src.platform.dependencies import get_db_session
from src.platform.exceptions import WebAppError
from src.ops.schemas.runtime import RuntimeTickRequest


router = APIRouter(prefix="/ops/runtime", tags=["ops"])


@router.post("/scheduler-tick")
def ops_scheduler_tick(
    body: RuntimeTickRequest,
    _user: AuthenticatedUser = Depends(require_admin),
    _session=Depends(get_db_session),
):
    raise WebAppError(
        status_code=409,
        code="runtime_decoupled",
        message="请通过独立调度器进程处理自动任务，不再由 Web 服务直接执行。",
    )


@router.post("/worker-run")
def ops_worker_run(
    body: RuntimeTickRequest,
    _user: AuthenticatedUser = Depends(require_admin),
    _session=Depends(get_db_session),
):
    raise WebAppError(
        status_code=409,
        code="runtime_decoupled",
        message="请通过独立执行器进程处理等待中的任务，不再由 Web 服务直接执行。",
    )
