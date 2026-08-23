from __future__ import annotations

from src.app.exceptions import WebAppError
from src.ops.contracts.external_task import ExternalTaskDefinition
from src.ops.services.task_run_service import TaskRunCreateContext


QTF_TASK_TYPE = "qtf_experiment"
QTF_RESOURCE_KEY = "sector_heat_research"
QTF_ACTION = "execute_backtest"


def build_qtf_task_definition() -> ExternalTaskDefinition:
    return ExternalTaskDefinition(
        task_type=QTF_TASK_TYPE,
        validate_context=_validate_qtf_context,
        resolve_title=lambda _context: "二级行业量化回测",
    )


def _validate_qtf_context(raw_context: object) -> None:
    if not isinstance(raw_context, TaskRunCreateContext):
        raise WebAppError(status_code=422, code="QTF_REQUEST_INVALID", message="量化任务上下文非法")
    context = raw_context
    if context.resource_key != QTF_RESOURCE_KEY or context.action != QTF_ACTION:
        raise WebAppError(status_code=422, code="QTF_REQUEST_INVALID", message="量化任务身份非法")
    if context.time_input or context.filters or context.schedule_id is not None:
        raise WebAppError(status_code=422, code="QTF_REQUEST_INVALID", message="量化任务不能携带调度或数据维护参数")
    payload = context.request_payload or {}
    if set(payload) != {"runKey", "revisionKey", "revisionHash"}:
        raise WebAppError(status_code=422, code="QTF_REQUEST_INVALID", message="量化任务请求字段不完整")
    if any(not isinstance(payload[key], str) or not str(payload[key]).strip() for key in payload):
        raise WebAppError(status_code=422, code="QTF_REQUEST_INVALID", message="量化任务请求字段非法")
