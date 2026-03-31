from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.operations.specs import get_ops_spec_display_name
from src.web.auth.dependencies import require_admin
from src.web.dependencies import get_db_session
from src.web.domain.user import AuthenticatedUser
from src.web.schemas.ops.runtime import RuntimeExecutionItem, RuntimeTickRequest, SchedulerTickResponse, WorkerRunResponse
from src.web.services.ops import OpsRuntimeCommandService


router = APIRouter(prefix="/ops/runtime", tags=["ops"])


def _runtime_item(execution) -> RuntimeExecutionItem:  # type: ignore[no-untyped-def]
    return RuntimeExecutionItem(
        id=execution.id,
        schedule_id=execution.schedule_id,
        spec_type=execution.spec_type,
        spec_key=execution.spec_key,
        spec_display_name=get_ops_spec_display_name(execution.spec_type, execution.spec_key),
        trigger_source=execution.trigger_source,
        status=execution.status,
        requested_at=execution.requested_at,
        rows_fetched=execution.rows_fetched,
        rows_written=execution.rows_written,
        summary_message=execution.summary_message,
    )


@router.post("/scheduler-tick", response_model=SchedulerTickResponse)
def ops_scheduler_tick(
    body: RuntimeTickRequest,
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> SchedulerTickResponse:
    executions = OpsRuntimeCommandService().scheduler_tick(session, limit=body.limit)
    return SchedulerTickResponse(
        scheduled_count=len(executions),
        items=[_runtime_item(execution) for execution in executions],
    )


@router.post("/worker-run", response_model=WorkerRunResponse)
def ops_worker_run(
    body: RuntimeTickRequest,
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> WorkerRunResponse:
    executions = OpsRuntimeCommandService().worker_run(session, limit=body.limit)
    return WorkerRunResponse(
        processed_count=len(executions),
        items=[_runtime_item(execution) for execution in executions],
    )
