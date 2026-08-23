from __future__ import annotations

from collections.abc import Callable, Mapping

from sqlalchemy.orm import Session

from qtf.adapters.persistence.repositories.research_repository import SqlAlchemyResearchRepository
from qtf.adapters.persistence.repositories.runtime_repository import SqlAlchemyRuntimeRepository
from qtf.adapters.prod.sector_source_adapter import ProdSectorInputSource
from qtf.modules.sector.executor import SectorExperimentExecutor
from src.ops.contracts.external_task import ExternalTaskExecutionOutcome
from src.ops.models.ops.task_run import TaskRun
from src.ops.services.task_run_progress_service import TaskRunProgressService


SessionFactory = Callable[[], Session]


class QtfTaskExecutor:
    def __init__(self, *, session_factory: SessionFactory, release_commit: str) -> None:
        self._session_factory = session_factory
        self._release_commit = release_commit

    def execute(
        self,
        *,
        task_run_id: int,
        request_payload: Mapping[str, object],
    ) -> ExternalTaskExecutionOutcome:
        run_key = request_payload.get("runKey")
        revision_key = request_payload.get("revisionKey")
        revision_hash = request_payload.get("revisionHash")
        if not isinstance(run_key, str) or not run_key.strip():
            return ExternalTaskExecutionOutcome(
                status="failed",
                summary_message="量化任务缺少 Run 标识。",
                status_reason_code="QTF_REQUEST_INVALID",
            )
        if not isinstance(revision_key, str) or not isinstance(revision_hash, str):
            return ExternalTaskExecutionOutcome(
                status="failed",
                summary_message="量化任务缺少冻结版本标识。",
                status_reason_code="QTF_REQUEST_INVALID",
            )
        business_session = self._session_factory()
        try:
            executor = SectorExperimentExecutor(
                research_repository=SqlAlchemyResearchRepository(business_session),
                runtime_repository=SqlAlchemyRuntimeRepository(business_session),
                input_source=ProdSectorInputSource(self._session_factory),
                unit_of_work=_SqlAlchemyUnitOfWork(business_session),
                observer=_TaskRunObserver(TaskRunProgressService(self._session_factory)),
                cancellation_probe=_TaskRunCancellationProbe(self._session_factory),
                release_commit=self._release_commit,
            )
            outcome = executor.execute(
                run_key=run_key,
                task_run_id=task_run_id,
                expected_revision_key=revision_key,
                expected_revision_hash=revision_hash,
            )
            return ExternalTaskExecutionOutcome(
                status=outcome.status,
                summary_message=outcome.summary_message,
                status_reason_code=outcome.status_reason_code,
            )
        finally:
            business_session.close()


class _SqlAlchemyUnitOfWork:
    def __init__(self, session: Session) -> None:
        self._session = session

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()


class _TaskRunObserver:
    def __init__(self, service: TaskRunProgressService) -> None:
        self._service = service

    def stage(self, *, task_run_id: int, stage_key: str, title: str, sequence_no: int) -> None:
        self._service.stage(task_run_id=task_run_id, stage_key=stage_key, title=title, sequence_no=sequence_no)

    def progress(
        self,
        *,
        task_run_id: int,
        stage_key: str,
        completed: int,
        total: int,
        message: str,
    ) -> None:
        self._service.progress(
            task_run_id=task_run_id,
            stage_key=stage_key,
            completed=completed,
            total=total,
            message=message,
        )

    def issue(self, *, task_run_id: int, code: str, message: str) -> None:
        self._service.issue(task_run_id=task_run_id, code=code, message=message)


class _TaskRunCancellationProbe:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def is_cancel_requested(self, task_run_id: int) -> bool:
        with self._session_factory() as session:
            task_run = session.get(TaskRun, task_run_id)
            return task_run is not None and task_run.cancel_requested_at is not None
