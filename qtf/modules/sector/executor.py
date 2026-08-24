from __future__ import annotations

import re
import time
import tracemalloc
from dataclasses import dataclass
from datetime import date, datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from platform import python_version

from qtf.application.ports.input_source import SectorInputSource
from qtf.application.ports.repositories import ResearchRepository, RuntimeRepository
from qtf.application.ports.runtime import CancellationProbe, RunObserver, RunUnitOfWork
from qtf.contracts.errors import (
    QtfInputChangedDuringRun,
    QtfPlanBudgetExceeded,
    QtfStateConflict,
)
from qtf.contracts.research import ExperimentRevisionStatus
from qtf.contracts.runtime import (
    ExperimentRunStatus,
    InputPreflightPhase,
    InputPreflightStatus,
    ValidationStatus,
)
from qtf.engine.canonical_hash import canonical_json_hash
from qtf.modules.sector.factor_kernel import SectorObservation, SectorUniverse, compute_sector_heat
from qtf.modules.sector.input_contract import SECTOR_L2_SOURCE_CONTRACT, SectorInputRequest
from qtf.modules.sector.input_preflight import evaluate_sector_input_with_matrix
from qtf.modules.sector.parameter_schema import resolve_sector_heat_parameters


_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True, slots=True)
class QtfExecutionOutcome:
    status: str
    summary_message: str
    status_reason_code: str | None = None
    observer_degraded: bool = False


class SectorExperimentExecutor:
    def __init__(
        self,
        *,
        research_repository: ResearchRepository,
        runtime_repository: RuntimeRepository,
        input_source: SectorInputSource,
        unit_of_work: RunUnitOfWork,
        observer: RunObserver,
        cancellation_probe: CancellationProbe,
        release_commit: str,
    ) -> None:
        self._research_repository = research_repository
        self._runtime_repository = runtime_repository
        self._input_source = input_source
        self._unit_of_work = unit_of_work
        self._observer = observer
        self._cancellation_probe = cancellation_probe
        self._release_commit = release_commit.strip().lower()
        self._observer_degraded = False

    def execute(
        self,
        *,
        run_key: str,
        task_run_id: int,
        expected_revision_key: str | None = None,
        expected_revision_hash: str | None = None,
    ) -> QtfExecutionOutcome:
        if not _COMMIT_PATTERN.fullmatch(self._release_commit):
            return self._fail_before_read(
                run_key,
                code="QTF_RUN_FAILED",
                message="QTF worker 缺少有效发布提交版本。",
            )
        run = self._runtime_repository.get_run_by_key(run_key)
        if run.status is not ExperimentRunStatus.QUEUED:
            return QtfExecutionOutcome(
                status="failed",
                summary_message="当前 Run 状态不允许执行。",
                status_reason_code="QTF_STATE_CONFLICT",
            )
        bundle = self._research_repository.get_bundle_by_revision_id(run.revision_id)
        revision = bundle.revision
        if revision.status is not ExperimentRevisionStatus.FROZEN or revision.revision_hash is None:
            return self._fail_before_read(run_key, code="QTF_STATE_CONFLICT", message="运行版本不是已冻结版本。")
        if expected_revision_key is not None and expected_revision_key != revision.revision_key:
            return self._fail_before_read(run_key, code="QTF_STATE_CONFLICT", message="TaskRun 与运行版本不一致。")
        if expected_revision_hash is not None and expected_revision_hash != revision.revision_hash:
            return self._fail_before_read(run_key, code="QTF_STATE_CONFLICT", message="TaskRun 与冻结内容不一致。")

        fingerprint = {
            "code_commit": self._release_commit,
            "python_version": python_version(),
            "qtf_version": _package_version(),
        }
        started_at = datetime.now(timezone.utc)
        self._runtime_repository.update_run(
            run_key,
            status=ExperimentRunStatus.EXECUTING.value,
            code_commit=self._release_commit,
            runtime_fingerprint_json=fingerprint,
            started_at=started_at,
            failure_code=None,
            failure_message=None,
        )
        self._unit_of_work.commit()
        self._observe_stage(task_run_id, "RUN_PREFLIGHT", "运行输入门禁", 1)

        try:
            matrix = _frozen_matrix(revision.content.effective_params)
            input_scope = revision.content.budget.get("input_scope")
            if not isinstance(input_scope, dict):
                raise QtfStateConflict("frozen revision is missing input scope")
            evaluation_calendar = revision.content.validation_spec.get("evaluation_calendar")
            if not isinstance(evaluation_calendar, dict):
                raise QtfStateConflict("frozen revision is missing evaluation calendar")
            requested_start_date = date.fromisoformat(
                str(evaluation_calendar["requested_evaluation_start_date"])
            )
            requested_end_date = date.fromisoformat(
                str(evaluation_calendar["requested_evaluation_end_date"])
            )
            request = SectorInputRequest(
                start_date=date.fromisoformat(str(input_scope["effective_start_date"])),
                end_date=date.fromisoformat(str(input_scope["effective_end_date"])),
                statement_timeout_ms=int(revision.content.budget["sourceStatementTimeoutMs"]),
            )
            # The single source read for this Run. All parameter sets use this immutable snapshot.
            snapshot = self._input_source.read(request)
            if snapshot.source_contract_hash != canonical_json_hash(SECTOR_L2_SOURCE_CONTRACT):
                raise QtfInputChangedDuringRun("source contract changed after plan approval")
            evaluation = evaluate_sector_input_with_matrix(
                snapshot,
                parameter_matrix=matrix,
                success_definition=revision.content.success_definition,
            )
            run_preflight = self._runtime_repository.create_preflight(
                preflight_key=f"qtf_preflight_{canonical_json_hash({'run_key': run_key})[:32]}",
                request_key=f"qtf_run_preflight_{canonical_json_hash({'run_key': run_key})[:32]}",
                revision_id=revision.id,
                draft_hash=None,
                phase=InputPreflightPhase.RUN_PREFLIGHT.value,
                status=evaluation.status.value,
                source_contract_hash=snapshot.source_contract_hash,
                as_of=snapshot.as_of,
                requested_start_date=requested_start_date,
                requested_end_date=requested_end_date,
                effective_start_date=snapshot.trade_dates[0] if snapshot.trade_dates else None,
                effective_end_date=snapshot.trade_dates[-1] if snapshot.trade_dates else None,
                dataset_evidence=[_jsonable(item.as_dict()) for item in snapshot.dataset_evidence],
                universe_count=len([node for node in snapshot.hierarchy if node.industry_level == 2]),
                group_count=len(evaluation.group_members),
                valid_group_day_count=len(evaluation.valid_group_days),
                excluded_group_day_count=evaluation.excluded_group_day_count,
                plan_estimate={},
                content_hash=snapshot.content_hash,
                completed_at=snapshot.as_of,
                issues=evaluation.issues,
            )
            self._runtime_repository.update_run(
                run_key,
                input_preflight_id=run_preflight.id,
                source_content_hash=snapshot.content_hash,
            )
            self._unit_of_work.commit()
            if evaluation.status is InputPreflightStatus.BLOCKED:
                return self._finish_blocked(run_key, task_run_id, "QTF_INPUT_PREFLIGHT_BLOCKED", "本次运行输入门禁未通过。")
            approved_source_hash = str(input_scope.get("source_content_hash") or "")
            if snapshot.content_hash != approved_source_hash:
                raise QtfInputChangedDuringRun("source content changed after plan approval")
            _assert_scope_budget(
                revision.content.budget,
                source_rows=sum(item.row_count for item in snapshot.dataset_evidence),
                group_days=len(evaluation.valid_group_days) + evaluation.excluded_group_day_count,
                parameter_count=len(matrix),
            )

            self._observe_stage(task_run_id, "LOAD_INPUT", "加载运行输入", 2)
            observations = _attach_parents(snapshot.observations, evaluation.group_members)
            self._observe_stage(task_run_id, "RUN_PARAMETER_SETS", "计算参数组合", 3)
            clock_started = time.monotonic()
            owns_trace = not tracemalloc.is_tracing()
            if owns_trace:
                tracemalloc.start()
            try:
                for index, parameter_set in enumerate(matrix, start=1):
                    if self._cancellation_probe.is_cancel_requested(task_run_id):
                        return self._finish_canceled(run_key, task_run_id)
                    values = parameter_set["values"]
                    sources = parameter_set["sources"]
                    if not isinstance(values, dict) or not isinstance(sources, dict):
                        raise QtfStateConflict("frozen parameter set is malformed")
                    parameters = resolve_sector_heat_parameters(values, sources).parameters
                    compute_sector_heat(
                        universe=SectorUniverse.EASTMONEY_INDUSTRY_L2,
                        trade_dates=snapshot.trade_dates,
                        group_members=evaluation.group_members,
                        observations=observations,
                        parameters=parameters,
                    )
                    self._runtime_repository.update_run(
                        run_key,
                        completed_parameter_set_count=index,
                    )
                    self._unit_of_work.commit()
                    self._observe_progress(
                        task_run_id,
                        "RUN_PARAMETER_SETS",
                        index,
                        len(matrix),
                        f"已完成 {index}/{len(matrix)} 个参数组合",
                    )
                    peak_mb = tracemalloc.get_traced_memory()[1] // (1024 * 1024) if tracemalloc.is_tracing() else 0
                    _assert_runtime_budget(
                        revision.content.budget,
                        elapsed_seconds=time.monotonic() - clock_started,
                        peak_memory_mb=peak_mb,
                    )
                    if self._cancellation_probe.is_cancel_requested(task_run_id):
                        return self._finish_canceled(run_key, task_run_id)
            finally:
                if owns_trace and tracemalloc.is_tracing():
                    tracemalloc.stop()

            self._observe_stage(task_run_id, "VALIDATE", "等待可信门禁", 4)
            self._observe_stage(task_run_id, "SUMMARIZE", "等待结果汇总", 5)
            self._observe_stage(task_run_id, "FINALIZE", "完成执行", 6)
            self._runtime_repository.update_run(
                run_key,
                status=ExperimentRunStatus.COMPLETED.value,
                validation_status=ValidationStatus.PENDING.value,
                runtime_fingerprint_json=self._observer_fingerprint(fingerprint),
                ended_at=datetime.now(timezone.utc),
            )
            self._unit_of_work.commit()
            return QtfExecutionOutcome(
                status="success",
                summary_message="参数组合计算完成，可信验证等待 M4。",
                observer_degraded=self._observer_degraded,
            )
        except QtfInputChangedDuringRun:
            return self._finish_blocked(run_key, task_run_id, "QTF_INPUT_CHANGED_DURING_RUN", "输入内容在计划批准后发生变化，请新建 Run。")
        except QtfPlanBudgetExceeded:
            return self._finish_blocked(run_key, task_run_id, "QTF_PLAN_BUDGET_EXCEEDED", "实际工作量超过获批预算。")
        except Exception:
            self._unit_of_work.rollback()
            return self._finish_failed(run_key, task_run_id, "QTF_RUN_FAILED", "量化运行失败，请查看 Ops 技术诊断。")

    def _fail_before_read(self, run_key: str, *, code: str, message: str) -> QtfExecutionOutcome:
        self._runtime_repository.update_run(
            run_key,
            status=ExperimentRunStatus.FAILED.value,
            failure_code=code,
            failure_message=message,
            ended_at=datetime.now(timezone.utc),
        )
        self._unit_of_work.commit()
        return QtfExecutionOutcome(status="failed", summary_message=message, status_reason_code=code)

    def _finish_blocked(self, run_key: str, task_run_id: int, code: str, message: str) -> QtfExecutionOutcome:
        self._observe_issue(task_run_id, code, message)
        current = self._runtime_repository.get_run_by_key(run_key)
        self._runtime_repository.update_run(
            run_key,
            status=ExperimentRunStatus.BLOCKED.value,
            validation_status=ValidationStatus.BLOCKED.value,
            failure_code=code,
            failure_message=message,
            runtime_fingerprint_json=self._observer_fingerprint(current.runtime_fingerprint),
            ended_at=datetime.now(timezone.utc),
        )
        self._unit_of_work.commit()
        return QtfExecutionOutcome(status="failed", summary_message=message, status_reason_code=code, observer_degraded=self._observer_degraded)

    def _finish_failed(self, run_key: str, task_run_id: int, code: str, message: str) -> QtfExecutionOutcome:
        self._observe_issue(task_run_id, code, message)
        current = self._runtime_repository.get_run_by_key(run_key)
        self._runtime_repository.update_run(
            run_key,
            status=ExperimentRunStatus.FAILED.value,
            failure_code=code,
            failure_message=message,
            runtime_fingerprint_json=self._observer_fingerprint(current.runtime_fingerprint),
            ended_at=datetime.now(timezone.utc),
        )
        self._unit_of_work.commit()
        return QtfExecutionOutcome(status="failed", summary_message=message, status_reason_code=code, observer_degraded=self._observer_degraded)

    def _finish_canceled(self, run_key: str, task_run_id: int) -> QtfExecutionOutcome:
        message = "运行已在参数组合安全点停止。"
        self._observe_issue(task_run_id, "canceled", message)
        current = self._runtime_repository.get_run_by_key(run_key)
        self._runtime_repository.update_run(
            run_key,
            status=ExperimentRunStatus.CANCELED.value,
            runtime_fingerprint_json=self._observer_fingerprint(current.runtime_fingerprint),
            ended_at=datetime.now(timezone.utc),
        )
        self._unit_of_work.commit()
        return QtfExecutionOutcome(status="canceled", summary_message=message, status_reason_code="canceled", observer_degraded=self._observer_degraded)

    def _observe_stage(self, task_run_id: int, stage_key: str, title: str, sequence_no: int) -> None:
        try:
            self._observer.stage(task_run_id=task_run_id, stage_key=stage_key, title=title, sequence_no=sequence_no)
        except Exception:
            self._observer_degraded = True

    def _observe_progress(self, task_run_id: int, stage_key: str, completed: int, total: int, message: str) -> None:
        try:
            self._observer.progress(
                task_run_id=task_run_id,
                stage_key=stage_key,
                completed=completed,
                total=total,
                message=message,
            )
        except Exception:
            self._observer_degraded = True

    def _observe_issue(self, task_run_id: int, code: str, message: str) -> None:
        try:
            self._observer.issue(task_run_id=task_run_id, code=code, message=message)
        except Exception:
            self._observer_degraded = True

    def _observer_fingerprint(self, current: dict[str, object]) -> dict[str, object]:
        return {
            **current,
            "observer_status": "DEGRADED" if self._observer_degraded else "NORMAL",
        }


def _frozen_matrix(value: dict[str, object]) -> tuple[dict[str, object], ...]:
    if set(value) != {"parameter_matrix", "fixed_parameters", "future_horizons", "comparison_scope"}:
        raise QtfStateConflict("frozen effective parameters are incomplete")
    matrix = value["parameter_matrix"]
    if not isinstance(matrix, list) or not matrix or not all(isinstance(item, dict) for item in matrix):
        raise QtfStateConflict("frozen parameter matrix is incomplete")
    return tuple(matrix)


def _attach_parents(
    observations: tuple[SectorObservation, ...],
    group_members: dict[str, tuple[str, ...]],
) -> tuple[SectorObservation, ...]:
    parent_by_sector = {sector: parent for parent, members in group_members.items() for sector in members}
    return tuple(
        SectorObservation(
            trade_date=row.trade_date,
            sector_code=row.sector_code,
            parent_sector_code=parent_by_sector[row.sector_code],
            pct_change=row.pct_change,
            amount=row.amount,
        )
        for row in observations
        if row.sector_code in parent_by_sector
    )


def _assert_scope_budget(budget: dict[str, object], *, source_rows: int, group_days: int, parameter_count: int) -> None:
    checks = {
        "estimatedSourceRows": source_rows,
        "estimatedGroupDays": group_days,
        "parameterCombinationCount": parameter_count,
        "executionPassCount": parameter_count,
    }
    for key, actual in checks.items():
        if actual > int(budget[key]):
            raise QtfPlanBudgetExceeded(f"{key} exceeded")


def _assert_runtime_budget(budget: dict[str, object], *, elapsed_seconds: float, peak_memory_mb: int) -> None:
    if elapsed_seconds > int(budget["estimatedRuntimeSeconds"]):
        raise QtfPlanBudgetExceeded("estimatedRuntimeSeconds exceeded")
    if peak_memory_mb > int(budget["peakMemoryMb"]):
        raise QtfPlanBudgetExceeded("peakMemoryMb exceeded")


def _jsonable(value: object) -> object:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _package_version() -> str:
    try:
        return version("goldenshare-market-data-platform")
    except PackageNotFoundError:
        return "development"
