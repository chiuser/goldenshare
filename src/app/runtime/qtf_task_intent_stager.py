from __future__ import annotations

from sqlalchemy.orm import Session

from qtf.application.ports.runtime import TaskRunIntent
from src.app.runtime.qtf_task_definition_adapter import build_qtf_task_definition
from src.ops.services.task_run_service import TaskRunCommandService, TaskRunCreateContext


class QtfTaskRunIntentStager:
    def __init__(self, session: Session) -> None:
        self._session = session
        definition = build_qtf_task_definition()
        self._service = TaskRunCommandService(
            external_task_definitions={definition.task_type: definition}
        )

    def stage(self, intent: TaskRunIntent) -> int:
        task_run = self._service.stage_task_run(
            self._session,
            context=TaskRunCreateContext(
                task_type=intent.task_type,
                resource_key=intent.resource_key,
                action=intent.action,
                time_input={},
                filters={},
                request_payload=dict(intent.request_payload),
                trigger_source="manual",
                requested_by_user_id=intent.requested_by_user_id,
                schedule_id=None,
            ),
        )
        return task_run.id
