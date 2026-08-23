from __future__ import annotations

from copy import deepcopy

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from qtf.adapters.persistence.repositories.research_repository import SqlAlchemyResearchRepository
from qtf.adapters.persistence.repositories.runtime_repository import SqlAlchemyRuntimeRepository
from qtf.adapters.prod.sector_source_adapter import ProdSectorInputSource
from qtf.api.schemas.research import (
    CreateResearchRequest,
    DatasetEvidenceView,
    FreezePlanResponse,
    FreezeResearchRequest,
    InputIssueView,
    InputPreflightRequest,
    ParameterSelectionsRequest,
    PlanView,
    PreflightView,
    ResearchEditorResponse,
    ResearchTemplateView,
    SaveDraftRequest,
    ScopeView,
    TemplateListResponse,
    TemplateSummary,
)
from qtf.api.schemas.run import (
    CancelRunRequest,
    CreateRunRequest,
    FrozenPlanSummary,
    RunCreateResponse,
    RunDetailResponse,
    RunFailureView,
    RunProgressView,
    RunStageView,
    RunUpdateView,
)
from qtf.application.services.experiment_service import ExperimentService
from qtf.application.services.input_preflight_service import InputPreflightService
from qtf.application.services.plan_freeze_service import PlanFreezeService
from qtf.application.services.research_service import ResearchService
from qtf.contracts.errors import (
    QtfDraftConflict,
    QtfError,
    QtfInputPreflightBlocked,
    QtfPlanBudgetExceeded,
    QtfPlanNotApproved,
    QtfQueryFailed,
    QtfRequestConflict,
    QtfRequestInvalid,
    QtfStateConflict,
    QtfTemplateNotFound,
)
from qtf.contracts.research import CreateResearchCommand, ExperimentRevisionStatus, ResearchBundle, RevisionContent
from qtf.contracts.runtime import ExperimentRunStatus, InputPreflightRecord
from qtf.engine.canonical_hash import revision_content_hash
from qtf.modules.sector.input_contract import (
    SECTOR_L2_COMPARISON_SPEC,
    SECTOR_L2_SOURCE_CONTRACT,
    SECTOR_L2_UNIVERSE_SPEC,
)
from qtf.modules.sector.templates import SECTOR_L2_TEMPLATE, SECTOR_L2_TEMPLATE_KEY
from src.app.auth.dependencies import require_admin
from src.app.auth.domain import AuthenticatedUser
from src.app.dependencies.db import get_db_session
from src.app.exceptions import WebAppError
from src.app.runtime.qtf_task_intent_stager import QtfTaskRunIntentStager
from src.db import get_session_factory
from src.ops.models.ops.task_run import TaskRun
from src.ops.models.ops.task_run_node import TaskRunNode
from src.ops.services.task_run_service import TaskRunCommandService


router = APIRouter(prefix="/qtf", tags=["qtf"])


def get_qtf_input_source() -> ProdSectorInputSource:
    return ProdSectorInputSource(get_session_factory())


@router.get("/templates", response_model=TemplateListResponse)
def get_templates(
    _user: AuthenticatedUser = Depends(require_admin),
) -> TemplateListResponse:
    template = SECTOR_L2_TEMPLATE
    return TemplateListResponse(
        templates=[
            TemplateSummary(
                template_key=template.template_key,
                title=template.title,
                description="在同一一级父行业内研究直属二级行业逐渐转热信号。",
                capability_key=template.capability_key,
                formula_key=template.formula_key,
                formula_version=template.formula_version,
                parameter_schema_key=template.parameter_schema_key,
                parameter_schema_version=template.parameter_schema_version,
            )
        ]
    )


@router.post("/researches", response_model=ResearchEditorResponse)
def create_research(
    body: CreateResearchRequest,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> ResearchEditorResponse:
    if body.template_key != SECTOR_L2_TEMPLATE_KEY:
        _raise_web(QtfTemplateNotFound("research template does not exist"))
    repository = SqlAlchemyResearchRepository(session)
    try:
        bundle = ResearchService(repository).create_research(
            CreateResearchCommand(
                request_key=body.request_key,
                title=body.title,
                template_key=SECTOR_L2_TEMPLATE.template_key,
                capability_key=SECTOR_L2_TEMPLATE.capability_key,
                created_by_user_id=user.id,
                initial_revision=_initial_revision(),
            )
        )
        session.commit()
        return _research_response(bundle)
    except QtfError as exc:
        session.rollback()
        _raise_web(exc)


@router.get("/researches/{research_key}", response_model=ResearchEditorResponse)
def get_research(
    research_key: str,
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> ResearchEditorResponse:
    try:
        return _research_response(SqlAlchemyResearchRepository(session).get_bundle_by_research_key(research_key))
    except QtfError as exc:
        _raise_web(exc)


@router.put("/researches/{research_key}/draft", response_model=ResearchEditorResponse)
def save_research_draft(
    research_key: str,
    body: SaveDraftRequest,
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> ResearchEditorResponse:
    repository = SqlAlchemyResearchRepository(session)
    try:
        current = repository.get_bundle_by_research_key(research_key)
        content = current.revision.content
        bundle = ResearchService(repository).save_draft(
            revision_key=current.revision.revision_key,
            expected_draft_version=body.draft_version,
            content=RevisionContent(
                problem_statement=body.problem_statement,
                success_definition=_success_definition(body.success_definition_keys),
                non_goals=list(body.non_goal_keys),
                source_contract=deepcopy(content.source_contract),
                universe_spec=deepcopy(content.universe_spec),
                comparison_spec=deepcopy(content.comparison_spec),
                formula_key=content.formula_key,
                formula_version=content.formula_version,
                parameter_schema_key=content.parameter_schema_key,
                parameter_schema_version=content.parameter_schema_version,
                effective_params=_effective_params(body.parameter_selections),
                validation_spec={},
                budget={},
            ),
        )
        session.commit()
        return _research_response(bundle)
    except QtfError as exc:
        session.rollback()
        _raise_web(exc)


@router.post("/researches/{research_key}/input-preflights", response_model=FreezePlanResponse)
def create_input_preflight(
    research_key: str,
    body: InputPreflightRequest,
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    input_source: ProdSectorInputSource = Depends(get_qtf_input_source),
) -> FreezePlanResponse:
    research_repository = SqlAlchemyResearchRepository(session)
    try:
        bundle = research_repository.get_bundle_by_research_key(research_key)
        preflight = InputPreflightService(
            research_repository=research_repository,
            runtime_repository=SqlAlchemyRuntimeRepository(session),
            input_source=input_source,
        ).preview(
            research_key=research_key,
            request_key=body.request_key,
            draft_version=body.draft_version,
            requested_start_date=body.requested_start_date,
            requested_end_date=body.requested_end_date,
        )
        session.commit()
        return _freeze_plan_response(bundle, preflight)
    except QtfError as exc:
        session.rollback()
        _raise_web(exc)


@router.post("/researches/{research_key}/freeze", response_model=ResearchEditorResponse)
def freeze_research(
    research_key: str,
    body: FreezeResearchRequest,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> ResearchEditorResponse:
    _ = body.request_key  # Freeze is idempotent by the approved plan hash.
    try:
        bundle = PlanFreezeService(
            research_repository=SqlAlchemyResearchRepository(session),
            runtime_repository=SqlAlchemyRuntimeRepository(session),
        ).freeze(
            research_key=research_key,
            draft_version=body.draft_version,
            preflight_key=body.input_preflight_key,
            approved_plan_hash=body.approved_plan_hash,
            acknowledged_exclusions=body.acknowledged_exclusions,
            frozen_by_user_id=user.id,
        )
        session.commit()
        return _research_response(bundle)
    except QtfError as exc:
        session.rollback()
        _raise_web(exc)


@router.post("/revisions/{revision_key}/runs", response_model=RunCreateResponse)
def create_run(
    revision_key: str,
    body: CreateRunRequest,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> RunCreateResponse:
    try:
        run = ExperimentService(
            research_repository=SqlAlchemyResearchRepository(session),
            runtime_repository=SqlAlchemyRuntimeRepository(session),
            task_run_stager=QtfTaskRunIntentStager(session),
        ).create_run(
            revision_key=revision_key,
            request_key=body.request_key,
            revision_hash=body.revision_hash,
            requested_by_user_id=user.id,
        )
        session.commit()
        if run.task_run_id is None:
            raise AssertionError("queued QTF Run must have a TaskRun")
        return RunCreateResponse(
            run_key=run.run_key,
            run_status=run.status.value,
            validation_status=run.validation_status.value,
            task_run_id=run.task_run_id,
        )
    except QtfError as exc:
        session.rollback()
        _raise_web(exc)
    except Exception:
        session.rollback()
        raise


@router.get("/runs/{run_key}", response_model=RunDetailResponse)
def get_run(
    run_key: str,
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> RunDetailResponse:
    try:
        run = SqlAlchemyRuntimeRepository(session).get_run_by_key(run_key)
        bundle = SqlAlchemyResearchRepository(session).get_bundle_by_revision_id(run.revision_id)
        task_run = session.get(TaskRun, run.task_run_id) if run.task_run_id is not None else None
        nodes = tuple(
            session.scalars(
                select(TaskRunNode)
                .where(TaskRunNode.task_run_id == run.task_run_id)
                .order_by(TaskRunNode.sequence_no.asc(), TaskRunNode.id.asc())
            )
        ) if run.task_run_id is not None else ()
        return _run_detail(run, bundle, task_run, nodes)
    except QtfError as exc:
        _raise_web(exc)


@router.post("/runs/{run_key}/cancel", response_model=RunDetailResponse)
def cancel_run(
    run_key: str,
    body: CancelRunRequest,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> RunDetailResponse:
    _ = body.request_key, body.comment
    runtime_repository = SqlAlchemyRuntimeRepository(session)
    try:
        run = runtime_repository.get_run_by_key(run_key)
        if run.status is ExperimentRunStatus.CANCELED and body.current_version in {"QUEUED", "CANCELED"}:
            return get_run(run_key, user, session)
        if run.status.value != body.current_version:
            raise QtfStateConflict("run status changed; reload before canceling")
        if run.status not in {ExperimentRunStatus.QUEUED, ExperimentRunStatus.EXECUTING}:
            raise QtfStateConflict("only QUEUED or EXECUTING runs can be canceled")
        if run.task_run_id is None:
            raise QtfStateConflict("run does not have a TaskRun")
        task_run = TaskRunCommandService().request_cancel(
            session,
            task_run_id=run.task_run_id,
            requested_by_user_id=user.id,
        )
        if task_run.status == "canceled":
            runtime_repository.update_run(run_key, status=ExperimentRunStatus.CANCELED.value)
            session.commit()
        return get_run(run_key, user, session)
    except QtfError as exc:
        session.rollback()
        _raise_web(exc)


def _initial_revision() -> RevisionContent:
    template = SECTOR_L2_TEMPLATE
    return RevisionContent(
        problem_statement="",
        success_definition={},
        non_goals=[],
        source_contract=deepcopy(SECTOR_L2_SOURCE_CONTRACT),
        universe_spec=deepcopy(SECTOR_L2_UNIVERSE_SPEC),
        comparison_spec=deepcopy(SECTOR_L2_COMPARISON_SPEC),
        formula_key=template.formula_key,
        formula_version=template.formula_version,
        parameter_schema_key=template.parameter_schema_key,
        parameter_schema_version=template.parameter_schema_version,
        effective_params={"values": {}, "sources": {}},
        validation_spec={},
        budget={},
    )


def _success_definition(keys: list[str]) -> dict[str, object]:
    if not keys:
        return {}
    return {"selected_keys": keys, "future_horizons": [1, 3, 5]}


def _effective_params(selection: ParameterSelectionsRequest | None) -> dict[str, object]:
    if selection is None:
        return {"values": {}, "sources": {}}
    values = {
        "baseline_days": list(selection.baseline_days),
        "trend_days": list(selection.trend_days),
        "amount_lookback_days": selection.amount_lookback_days,
        "ewma_lambda": selection.ewma_lambda,
        "price_weight": selection.price_weight,
        "amount_weight": selection.amount_weight,
        "z_clip": selection.z_clip,
        "signal_threshold": selection.signal_threshold,
        "reset_threshold": selection.reset_threshold,
        "up_move_share_min": selection.up_move_share_min,
        "future_horizons": list(selection.future_horizons),
        "comparison_scope": selection.comparison_scope,
        "minimum_group_size": selection.minimum_group_size,
        "ranking_rule": selection.ranking_rule.model_dump(),
        "event_cluster_rule": selection.event_cluster_rule,
    }
    sources = {
        key: "CANDIDATE" if key in {"baseline_days", "trend_days"} else "FIXED"
        for key in values
    }
    return {"values": values, "sources": sources}


def _research_response(bundle: ResearchBundle) -> ResearchEditorResponse:
    revision = bundle.revision
    selection = _selection_from_content(revision.content)
    reasons: list[str] = []
    if revision.status is ExperimentRevisionStatus.DRAFT:
        if not revision.content.problem_statement.strip():
            reasons.append("研究问题尚未配置")
        if not revision.content.success_definition:
            reasons.append("成功定义尚未配置")
        if not revision.content.non_goals:
            reasons.append("非目标尚未配置")
        if selection is None:
            reasons.append("参数尚未完整配置")
    return ResearchEditorResponse(
        research_key=bundle.research.research_key,
        revision_key=revision.revision_key,
        revision_no=revision.revision_no,
        draft_version=revision.draft_version,
        revision_status=revision.status.value,
        research_status=bundle.research.status.value,
        title=bundle.research.title,
        template=ResearchTemplateView(
            template_key=SECTOR_L2_TEMPLATE.template_key,
            title=SECTOR_L2_TEMPLATE.title,
            description="在同一一级父行业内研究直属二级行业逐渐转热信号。",
            formula_key=revision.content.formula_key,
            parameter_schema_key=revision.content.parameter_schema_key,
        ),
        problem_statement=revision.content.problem_statement,
        success_definition_keys=list(revision.content.success_definition.get("selected_keys", [])),
        non_goal_keys=[str(item) for item in revision.content.non_goals],
        parameter_selections=selection,
        scope=ScopeView(
            source_kind="PROD",
            object_type="EASTMONEY_INDUSTRY_L2",
            comparison_scope="SIBLINGS",
            candidate_trend_days=[] if selection is None else list(selection.trend_days),
            candidate_baseline_days=[] if selection is None else list(selection.baseline_days),
            future_horizons=[1, 3, 5],
            shared_parameter_scope="ALL_L2_SECTORS",
            run_policy="READ_SOURCE_FOR_EACH_RUN",
            data_responsibility="PROD_OR_LAKE",
        ),
        revision_hash=revision.revision_hash,
        can_edit=revision.status is ExperimentRevisionStatus.DRAFT,
        can_preflight=revision.status is ExperimentRevisionStatus.DRAFT and not reasons,
        blocking_reasons=reasons,
        updated_at=revision.updated_at,
    )


def _selection_from_content(content: RevisionContent) -> ParameterSelectionsRequest | None:
    value = content.effective_params
    if set(value) == {"values", "sources"} and value["values"]:
        raw = dict(value["values"])  # type: ignore[arg-type]
        return ParameterSelectionsRequest.model_validate(raw)
    matrix = value.get("parameter_matrix")
    if not isinstance(matrix, list) or not matrix:
        return None
    first = matrix[0]
    if not isinstance(first, dict) or not isinstance(first.get("values"), dict):
        return None
    raw = dict(first["values"])
    raw["baseline_days"] = sorted({int(item["values"]["baseline_days"]) for item in matrix})
    raw["trend_days"] = sorted({int(item["values"]["trend_days"]) for item in matrix})
    return ParameterSelectionsRequest.model_validate(raw)


def _freeze_plan_response(bundle: ResearchBundle, preflight: InputPreflightRecord) -> FreezePlanResponse:
    plan = preflight.plan
    plan_payload = None
    if plan is not None:
        plan_payload = plan.as_dict()
        plan_payload.pop("input_scope")
        plan_payload.pop("estimator_inputs")
    return FreezePlanResponse(
        research_key=bundle.research.research_key,
        revision_key=bundle.revision.revision_key,
        draft_version=bundle.revision.draft_version,
        draft_hash=preflight.draft_hash or "",
        preflight=PreflightView(
            preflight_key=preflight.preflight_key,
            preflight_status=preflight.status.value,
            source_kind=preflight.source_kind.value,
            as_of=preflight.as_of,
            requested_start_date=preflight.requested_start_date,
            requested_end_date=preflight.requested_end_date,
            effective_start_date=preflight.effective_start_date,
            effective_end_date=preflight.effective_end_date,
            universe_count=preflight.universe_count,
            group_count=preflight.group_count,
            valid_group_day_count=preflight.valid_group_day_count,
            excluded_group_day_count=preflight.excluded_group_day_count,
            dataset_evidence=[DatasetEvidenceView(**item.as_dict()) for item in preflight.dataset_evidence],
            issues=[
                InputIssueView(
                    code=item.code,
                    severity=item.severity,
                    dataset_key=item.dataset_key,
                    trade_date=item.trade_date,
                    field_name=item.field_name,
                    object_key=item.object_key,
                    message=item.message,
                    remediation_owner=item.remediation_owner.value,
                    evidence=item.evidence or {},
                )
                for item in preflight.issues
            ],
            content_hash=preflight.content_hash,
        ),
        plan=None if plan_payload is None else PlanView(**plan_payload),
        can_freeze=plan is not None and preflight.status.value == "PASS",
        blocking_reasons=[] if plan is not None else ["输入门禁未通过"],
    )


def _run_detail(run, bundle: ResearchBundle, task_run: TaskRun | None, nodes: tuple[TaskRunNode, ...]) -> RunDetailResponse:  # type: ignore[no-untyped-def]
    matrix = bundle.revision.content.effective_params.get("parameter_matrix", [])
    input_scope = bundle.revision.content.budget.get("input_scope", {})
    validation = bundle.revision.content.validation_spec
    current_stage = None
    if task_run is not None and isinstance(task_run.current_object_json, dict):
        current_stage = task_run.current_object_json.get("stageKey")
    latest_updates = [
        RunUpdateView(
            occurred_at=node.updated_at,
            stage_key=node.node_key,
            message=str(node.context_json.get("message") or node.title),
        )
        for node in nodes[-10:]
    ]
    terminal = run.status in {
        ExperimentRunStatus.COMPLETED,
        ExperimentRunStatus.FAILED,
        ExperimentRunStatus.CANCELED,
        ExperimentRunStatus.BLOCKED,
    }
    failure = None
    if run.failure_code:
        failure = RunFailureView(
            code=run.failure_code,
            message=run.failure_message or "运行未完成",
            retryable=False,
        )
    return RunDetailResponse(
        run_key=run.run_key,
        research_key=bundle.research.research_key,
        revision_key=bundle.revision.revision_key,
        revision_no=bundle.revision.revision_no,
        run_status=run.status.value,
        validation_status=run.validation_status.value,
        formula_version=run.formula_version,
        code_commit=run.code_commit,
        source_content_hash=run.source_content_hash,
        started_at=run.started_at,
        ended_at=run.ended_at,
        progress=RunProgressView(
            percent=None if task_run is None else task_run.progress_percent,
            completed_parameter_set_count=run.completed_parameter_set_count,
            total_parameter_set_count=len(matrix) if isinstance(matrix, list) else 0,
            current_stage_key=None if current_stage is None else str(current_stage),
            can_cancel=not terminal,
            observer_status=str(run.runtime_fingerprint.get("observer_status", "NORMAL")),
            latest_updates=latest_updates,
        ),
        stages=[
            RunStageView(
                stage_key=node.node_key,
                label=node.title,
                status=node.status,
                summary=str(node.context_json.get("message")) if node.context_json.get("message") else None,
            )
            for node in nodes
        ],
        frozen_plan_summary=FrozenPlanSummary(
            object_count=int(input_scope.get("universe_count", 0)) if isinstance(input_scope, dict) else 0,
            comparison_scope=str(bundle.revision.content.effective_params.get("comparison_scope", "SIBLINGS")),
            candidate_count=len(matrix) if isinstance(matrix, list) else 0,
            sample_split=dict(validation.get("sample_split", {})),
            source_kind="PROD",
        ),
        failure=failure,
    )


def _raise_web(exc: QtfError) -> None:
    status = 422
    if isinstance(exc, (QtfDraftConflict, QtfRequestConflict, QtfStateConflict, QtfPlanNotApproved, QtfPlanBudgetExceeded, QtfInputPreflightBlocked)):
        status = 409
    if isinstance(exc, QtfTemplateNotFound) or "does not exist" in str(exc):
        status = 404
    if isinstance(exc, QtfQueryFailed):
        status = 503
    if isinstance(exc, QtfRequestInvalid):
        status = 422
    raise WebAppError(status_code=status, code=exc.code, message=_public_message(exc)) from exc


def _public_message(exc: QtfError) -> str:
    messages = {
        "QTF_TEMPLATE_NOT_FOUND": "研究模板不存在。",
        "QTF_DRAFT_CONFLICT": "草稿已变化，请刷新后重试。",
        "QTF_STATE_CONFLICT": "当前状态不允许该操作。",
        "QTF_INPUT_PREFLIGHT_BLOCKED": "输入门禁未通过。",
        "QTF_PLAN_NOT_APPROVED": "当前 PLAN 尚未获得确认。",
        "QTF_PLAN_BUDGET_EXCEEDED": "本次计划超过已确认预算。",
        "QTF_QUERY_FAILED": "输入数据读取失败，请稍后重试。",
        "QTF_REQUEST_INVALID": "请求内容不符合量化研究合同。",
    }
    return messages.get(exc.code, "量化平台请求未完成。")
