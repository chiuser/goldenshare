from __future__ import annotations

from qtf.application.ports.repositories import ResearchRepository, RuntimeRepository
from qtf.contracts.errors import (
    QtfDraftConflict,
    QtfInputPreflightBlocked,
    QtfPlanNotApproved,
    QtfRequestInvalid,
    QtfStateConflict,
)
from qtf.contracts.research import ExperimentRevisionStatus, ResearchBundle, RevisionContent
from qtf.contracts.runtime import InputPreflightPhase, InputPreflightStatus
from qtf.engine.canonical_hash import revision_content_hash
from qtf.modules.sector.input_preflight import execution_plan_hash
from qtf.modules.sector.input_contract import SECTOR_L2_COMPARISON_SPEC, SECTOR_L2_SOURCE_CONTRACT, SECTOR_L2_UNIVERSE_SPEC
from qtf.modules.sector.templates import SECTOR_L2_TEMPLATE


class PlanFreezeService:
    def __init__(self, *, research_repository: ResearchRepository, runtime_repository: RuntimeRepository) -> None:
        self._research_repository = research_repository
        self._runtime_repository = runtime_repository

    def freeze(
        self,
        *,
        research_key: str,
        draft_version: int,
        preflight_key: str,
        approved_plan_hash: str,
        acknowledged_exclusions: bool,
        frozen_by_user_id: int,
    ) -> ResearchBundle:
        bundle = self._research_repository.get_bundle_by_research_key(research_key)
        revision = bundle.revision
        if revision.status is ExperimentRevisionStatus.FROZEN:
            if revision.content.budget.get("plan_hash") == approved_plan_hash:
                return bundle
            raise QtfStateConflict("revision is already frozen with another plan")
        if revision.status is not ExperimentRevisionStatus.DRAFT:
            raise QtfStateConflict("only DRAFT revisions can be frozen")
        if revision.draft_version != draft_version:
            raise QtfDraftConflict("draft version changed; reload before freezing")
        preflight = self._runtime_repository.get_preflight_by_key(preflight_key)
        if preflight.revision_id != revision.id:
            raise QtfPlanNotApproved("input preflight belongs to another revision")
        latest_preflight = self._runtime_repository.get_latest_preflight_for_revision(
            revision.id,
            phase=InputPreflightPhase.DRAFT_PREVIEW.value,
        )
        if latest_preflight is None or latest_preflight.id != preflight.id:
            raise QtfPlanNotApproved("input preflight has been superseded")
        if preflight.draft_hash != revision_content_hash(revision.content):
            raise QtfDraftConflict("draft changed after input preflight")
        if preflight.status is not InputPreflightStatus.PASS or preflight.plan is None:
            raise QtfInputPreflightBlocked("input preflight is blocked")
        if preflight.excluded_group_day_count > 0 and not acknowledged_exclusions:
            raise QtfPlanNotApproved("excluded group days must be acknowledged")
        if execution_plan_hash(preflight.plan) != preflight.plan.plan_hash:
            raise QtfPlanNotApproved("stored plan content hash is invalid")
        if approved_plan_hash != preflight.plan.plan_hash:
            raise QtfPlanNotApproved("approved plan hash does not match the current plan")
        _validate_draft(revision.content)

        plan = preflight.plan
        frozen_content = RevisionContent(
            problem_statement=revision.content.problem_statement.strip(),
            success_definition=dict(revision.content.success_definition),
            non_goals=list(revision.content.non_goals),
            source_contract=dict(revision.content.source_contract),
            universe_spec=dict(revision.content.universe_spec),
            comparison_spec=dict(revision.content.comparison_spec),
            formula_key=revision.content.formula_key,
            formula_version=revision.content.formula_version,
            parameter_schema_key=revision.content.parameter_schema_key,
            parameter_schema_version=revision.content.parameter_schema_version,
            effective_params={
                "parameter_matrix": list(plan.parameter_matrix),
                "fixed_parameters": dict(plan.fixed_parameters),
                "future_horizons": list(plan.future_horizons),
                "comparison_scope": plan.comparison_scope,
            },
            validation_spec={
                "sample_split": dict(plan.sample_split),
                "primary_objective": plan.primary_objective,
                "success_definition": dict(plan.success_definition),
                "hard_gates": list(plan.hard_gates),
                "stop_conditions": list(plan.stop_conditions),
            },
            budget={
                **dict(plan.budget),
                "estimator_version": plan.estimator_version,
                "estimator_inputs": dict(plan.estimator_inputs),
                "plan_hash": plan.plan_hash,
                "input_scope": dict(plan.input_scope),
            },
        )
        revision_hash = revision_content_hash(frozen_content)
        return self._research_repository.freeze_revision(
            revision_key=revision.revision_key,
            expected_draft_version=draft_version,
            content=frozen_content,
            revision_hash=revision_hash,
            frozen_by_user_id=frozen_by_user_id,
        )


def _validate_draft(content: RevisionContent) -> None:
    if not content.problem_statement.strip():
        raise QtfRequestInvalid("problem statement must be completed before freezing")
    if not content.success_definition:
        raise QtfRequestInvalid("success definition must be completed before freezing")
    if set(content.non_goals) != {"PER_SECTOR_TUNING", "PRODUCTION_RELEASE"}:
        raise QtfRequestInvalid("registered non-goals must be explicitly confirmed")
    if content.source_contract != SECTOR_L2_SOURCE_CONTRACT:
        raise QtfRequestInvalid("source contract does not match the registered template")
    if content.universe_spec != SECTOR_L2_UNIVERSE_SPEC:
        raise QtfRequestInvalid("universe contract does not match the registered template")
    if content.comparison_spec != SECTOR_L2_COMPARISON_SPEC:
        raise QtfRequestInvalid("comparison contract does not match the registered template")
    template = SECTOR_L2_TEMPLATE
    if (
        content.formula_key != template.formula_key
        or content.formula_version != template.formula_version
        or content.parameter_schema_key != template.parameter_schema_key
        or content.parameter_schema_version != template.parameter_schema_version
    ):
        raise QtfRequestInvalid("formula or parameter schema identity does not match the registered template")
