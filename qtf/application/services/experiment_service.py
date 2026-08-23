from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from qtf.application.ports.repositories import ResearchRepository, RuntimeRepository
from qtf.application.ports.runtime import TaskRunIntent, TaskRunIntentStager
from qtf.contracts.errors import QtfRequestConflict, QtfRequestInvalid, QtfStateConflict
from qtf.contracts.research import ExperimentRevisionStatus
from qtf.contracts.runtime import ExperimentRunRecord


class ExperimentService:
    def __init__(
        self,
        *,
        research_repository: ResearchRepository,
        runtime_repository: RuntimeRepository,
        task_run_stager: TaskRunIntentStager,
        key_factory: Callable[[], str] | None = None,
    ) -> None:
        self._research_repository = research_repository
        self._runtime_repository = runtime_repository
        self._task_run_stager = task_run_stager
        self._key_factory = key_factory or (lambda: f"qtf_run_{uuid4().hex}")

    def create_run(
        self,
        *,
        revision_key: str,
        request_key: str,
        revision_hash: str,
        requested_by_user_id: int,
    ) -> ExperimentRunRecord:
        if not request_key.strip():
            raise QtfRequestInvalid("request_key is required")
        bundle = self._research_repository.get_bundle_by_revision_key(revision_key)
        revision = bundle.revision
        if revision.status is not ExperimentRevisionStatus.FROZEN or revision.revision_hash is None:
            raise QtfStateConflict("only FROZEN revisions can start a run")
        if revision.revision_hash != revision_hash:
            raise QtfStateConflict("revision hash changed; reload before starting")
        existing = self._runtime_repository.find_run_by_request_key(request_key)
        if existing is not None:
            if existing.revision_id != revision.id:
                raise QtfRequestConflict("request_key was already used for another revision")
            return existing

        run = self._runtime_repository.stage_run(
            run_key=self._key_factory(),
            request_key=request_key.strip(),
            revision_id=revision.id,
            formula_version=revision.content.formula_version,
        )
        task_run_id = self._task_run_stager.stage(
            TaskRunIntent(
                task_type="qtf_experiment",
                resource_key="sector_heat_research",
                action="execute_backtest",
                title=bundle.research.title,
                request_payload={
                    "runKey": run.run_key,
                    "revisionKey": revision.revision_key,
                    "revisionHash": revision.revision_hash,
                },
                requested_by_user_id=requested_by_user_id,
            )
        )
        return self._runtime_repository.link_queued_task_run(run.run_key, task_run_id=task_run_id)
