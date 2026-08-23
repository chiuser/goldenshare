from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from qtf.adapters.persistence.models.runtime import ExperimentRun, InputPreflight, InputPreflightIssue
from qtf.contracts.errors import QtfRequestConflict, QtfStateConflict
from qtf.contracts.runtime import (
    DatasetEvidence,
    ExecutionPlan,
    ExperimentRunRecord,
    ExperimentRunStatus,
    InputPreflightIssueRecord,
    InputPreflightPhase,
    InputPreflightRecord,
    InputPreflightStatus,
    InputSourceKind,
    RemediationOwner,
    ValidationStatus,
)


class SqlAlchemyRuntimeRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def find_preflight_by_request_key(self, request_key: str) -> InputPreflightRecord | None:
        row = self._session.scalar(
            select(InputPreflight).where(InputPreflight.request_key == request_key)
        )
        return None if row is None else self._preflight_record(row)

    def get_preflight_by_key(self, preflight_key: str) -> InputPreflightRecord:
        row = self._session.scalar(
            select(InputPreflight).where(InputPreflight.preflight_key == preflight_key)
        )
        if row is None:
            raise QtfStateConflict("input preflight does not exist")
        return self._preflight_record(row)

    def get_latest_preflight_for_revision(
        self,
        revision_id: int,
        *,
        phase: str,
    ) -> InputPreflightRecord | None:
        row = self._session.scalar(
            select(InputPreflight)
            .where(
                InputPreflight.revision_id == revision_id,
                InputPreflight.phase == phase,
            )
            .order_by(InputPreflight.completed_at.desc(), InputPreflight.id.desc())
            .limit(1)
        )
        return None if row is None else self._preflight_record(row)

    def create_preflight(
        self,
        *,
        preflight_key: str,
        request_key: str,
        revision_id: int,
        draft_hash: str | None,
        phase: str,
        status: str,
        source_contract_hash: str,
        as_of: datetime,
        requested_start_date: date,
        requested_end_date: date,
        effective_start_date: date | None,
        effective_end_date: date | None,
        dataset_evidence: list[dict[str, object]],
        universe_count: int,
        group_count: int,
        valid_group_day_count: int,
        excluded_group_day_count: int,
        plan_estimate: dict[str, object],
        content_hash: str,
        completed_at: datetime,
        issues: tuple[InputPreflightIssueRecord, ...],
    ) -> InputPreflightRecord:
        try:
            with self._session.begin_nested():
                row = InputPreflight(
                    preflight_key=preflight_key,
                    request_key=request_key,
                    revision_id=revision_id,
                    draft_hash=draft_hash,
                    phase=phase,
                    status=status,
                    source_kind=InputSourceKind.PROD.value,
                    source_contract_hash=source_contract_hash,
                    as_of=as_of,
                    requested_start_date=requested_start_date,
                    requested_end_date=requested_end_date,
                    effective_start_date=effective_start_date,
                    effective_end_date=effective_end_date,
                    dataset_evidence_json=deepcopy(dataset_evidence),
                    universe_count=universe_count,
                    group_count=group_count,
                    valid_group_day_count=valid_group_day_count,
                    excluded_group_day_count=excluded_group_day_count,
                    plan_estimate_json=deepcopy(plan_estimate),
                    content_hash=content_hash,
                    completed_at=completed_at,
                )
                self._session.add(row)
                self._session.flush()
                for issue in issues:
                    self._session.add(
                        InputPreflightIssue(
                            preflight_id=row.id,
                            code=issue.code,
                            severity=issue.severity,
                            dataset_key=issue.dataset_key,
                            trade_date=issue.trade_date,
                            field_name=issue.field_name,
                            object_key=issue.object_key,
                            message=issue.message,
                            remediation_owner=issue.remediation_owner.value,
                            evidence_json=deepcopy(issue.evidence or {}),
                        )
                    )
                self._session.flush()
            return self._preflight_record(row)
        except IntegrityError:
            existing = self.find_preflight_by_request_key(request_key)
            if existing is None:
                raise
            if (
                existing.revision_id != revision_id
                or existing.draft_hash != draft_hash
                or existing.phase.value != phase
                or existing.requested_start_date != requested_start_date
                or existing.requested_end_date != requested_end_date
            ):
                raise QtfRequestConflict("request_key was already used for a different preflight")
            return existing

    def find_run_by_request_key(self, request_key: str) -> ExperimentRunRecord | None:
        row = self._session.scalar(select(ExperimentRun).where(ExperimentRun.request_key == request_key))
        return None if row is None else _run_record(row)

    def get_run_by_key(self, run_key: str) -> ExperimentRunRecord:
        row = self._session.scalar(select(ExperimentRun).where(ExperimentRun.run_key == run_key))
        if row is None:
            raise QtfStateConflict("experiment run does not exist")
        return _run_record(row)

    def stage_run(
        self,
        *,
        run_key: str,
        request_key: str,
        revision_id: int,
        formula_version: str,
    ) -> ExperimentRunRecord:
        row = ExperimentRun(
            run_key=run_key,
            request_key=request_key,
            revision_id=revision_id,
            input_preflight_id=None,
            task_run_id=None,
            status=ExperimentRunStatus.PLANNED.value,
            validation_status=ValidationStatus.PENDING.value,
            code_commit=None,
            runtime_fingerprint_json={},
            formula_version=formula_version,
            source_content_hash=None,
            result_hash=None,
            completed_parameter_set_count=0,
        )
        self._session.add(row)
        self._session.flush()
        return _run_record(row)

    def link_queued_task_run(self, run_key: str, *, task_run_id: int) -> ExperimentRunRecord:
        row = self.get_run_model_by_key(run_key)
        _assert_run_status_transition(row.status, ExperimentRunStatus.QUEUED.value)
        row.task_run_id = task_run_id
        row.status = ExperimentRunStatus.QUEUED.value
        self._session.flush()
        return _run_record(row)

    def get_run_model_by_key(self, run_key: str) -> ExperimentRun:
        row = self._session.scalar(select(ExperimentRun).where(ExperimentRun.run_key == run_key))
        if row is None:
            raise QtfStateConflict("experiment run does not exist")
        return row

    def update_run(
        self,
        run_key: str,
        **changes: object,
    ) -> ExperimentRunRecord:
        allowed = {
            "input_preflight_id",
            "status",
            "validation_status",
            "code_commit",
            "runtime_fingerprint_json",
            "source_content_hash",
            "result_hash",
            "completed_parameter_set_count",
            "failure_code",
            "failure_message",
            "started_at",
            "ended_at",
        }
        unknown = sorted(set(changes) - allowed)
        if unknown:
            raise QtfStateConflict(f"unsupported experiment run fields: {unknown}")
        row = self.get_run_model_by_key(run_key)
        if "status" in changes:
            _assert_run_status_transition(row.status, str(changes["status"]))
        for key, value in changes.items():
            setattr(row, key, value)
        self._session.flush()
        return _run_record(row)

    def _preflight_record(self, row: InputPreflight) -> InputPreflightRecord:
        issue_rows = tuple(
            self._session.scalars(
                select(InputPreflightIssue)
                .where(InputPreflightIssue.preflight_id == row.id)
                .order_by(InputPreflightIssue.id.asc())
            )
        )
        plan = _plan_from_json(row.plan_estimate_json)
        return InputPreflightRecord(
            id=row.id,
            preflight_key=row.preflight_key,
            request_key=row.request_key,
            revision_id=row.revision_id,
            draft_hash=row.draft_hash,
            phase=InputPreflightPhase(row.phase),
            status=InputPreflightStatus(row.status),
            source_kind=InputSourceKind(row.source_kind),
            source_contract_hash=row.source_contract_hash,
            as_of=row.as_of,
            requested_start_date=row.requested_start_date,
            requested_end_date=row.requested_end_date,
            effective_start_date=row.effective_start_date,
            effective_end_date=row.effective_end_date,
            dataset_evidence=tuple(_dataset_evidence(item) for item in row.dataset_evidence_json),
            universe_count=row.universe_count,
            group_count=row.group_count,
            valid_group_day_count=row.valid_group_day_count,
            excluded_group_day_count=row.excluded_group_day_count,
            plan=plan,
            content_hash=row.content_hash,
            completed_at=row.completed_at,
            issues=tuple(
                InputPreflightIssueRecord(
                    code=issue.code,
                    severity=issue.severity,
                    dataset_key=issue.dataset_key,
                    trade_date=issue.trade_date,
                    field_name=issue.field_name,
                    object_key=issue.object_key,
                    message=issue.message,
                    remediation_owner=RemediationOwner(issue.remediation_owner),
                    evidence=deepcopy(issue.evidence_json),
                )
                for issue in issue_rows
            ),
        )


def _dataset_evidence(value: dict[str, object]) -> DatasetEvidence:
    return DatasetEvidence(
        dataset_key=str(value["dataset_key"]),
        fields=tuple(str(item) for item in value["fields"]),  # type: ignore[arg-type]
        start_date=date.fromisoformat(str(value["start_date"])) if value.get("start_date") else None,
        end_date=date.fromisoformat(str(value["end_date"])) if value.get("end_date") else None,
        row_count=int(value["row_count"]),
        unique_key_status=str(value["unique_key_status"]),
        missing_count=int(value["missing_count"]),
        duplicate_count=int(value["duplicate_count"]),
        content_hash=str(value["content_hash"]),
    )


def _plan_from_json(value: dict[str, object]) -> ExecutionPlan | None:
    if not value or "plan_hash" not in value:
        return None
    return ExecutionPlan(
        input_scope=deepcopy(value["input_scope"]),  # type: ignore[arg-type]
        estimator_inputs={key: int(item) for key, item in value["estimator_inputs"].items()},  # type: ignore[union-attr]
        parameter_matrix=tuple(deepcopy(value["parameter_matrix"])),  # type: ignore[arg-type]
        fixed_parameters=deepcopy(value["fixed_parameters"]),  # type: ignore[arg-type]
        future_horizons=tuple(int(item) for item in value["future_horizons"]),  # type: ignore[arg-type]
        comparison_scope=str(value["comparison_scope"]),
        sample_split=deepcopy(value["sample_split"]),  # type: ignore[arg-type]
        primary_objective=str(value["primary_objective"]),
        success_definition=deepcopy(value["success_definition"]),  # type: ignore[arg-type]
        hard_gates=tuple(str(item) for item in value["hard_gates"]),  # type: ignore[arg-type]
        stop_conditions=tuple(str(item) for item in value["stop_conditions"]),  # type: ignore[arg-type]
        budget={key: int(item) for key, item in value["budget"].items()},  # type: ignore[union-attr]
        estimator_version=str(value["estimator_version"]),
        plan_hash=str(value["plan_hash"]),
    )


def _run_record(row: ExperimentRun) -> ExperimentRunRecord:
    return ExperimentRunRecord(
        id=row.id,
        run_key=row.run_key,
        request_key=row.request_key,
        revision_id=row.revision_id,
        input_preflight_id=row.input_preflight_id,
        task_run_id=row.task_run_id,
        status=ExperimentRunStatus(row.status),
        validation_status=ValidationStatus(row.validation_status),
        code_commit=row.code_commit,
        runtime_fingerprint=deepcopy(row.runtime_fingerprint_json),
        formula_version=row.formula_version,
        source_content_hash=row.source_content_hash,
        result_hash=row.result_hash,
        completed_parameter_set_count=row.completed_parameter_set_count,
        failure_code=row.failure_code,
        failure_message=row.failure_message,
        started_at=row.started_at,
        ended_at=row.ended_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _assert_run_status_transition(current: str, target: str) -> None:
    if current == target:
        return
    allowed = {
        ExperimentRunStatus.PLANNED.value: {ExperimentRunStatus.QUEUED.value},
        ExperimentRunStatus.QUEUED.value: {
            ExperimentRunStatus.EXECUTING.value,
            ExperimentRunStatus.CANCELED.value,
            ExperimentRunStatus.FAILED.value,
        },
        ExperimentRunStatus.EXECUTING.value: {
            ExperimentRunStatus.COMPLETED.value,
            ExperimentRunStatus.FAILED.value,
            ExperimentRunStatus.CANCELED.value,
            ExperimentRunStatus.BLOCKED.value,
        },
    }
    if target not in allowed.get(current, set()):
        raise QtfStateConflict(f"unsupported experiment run transition: {current} -> {target}")
