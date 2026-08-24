from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date
from uuid import uuid4

from qtf.application.ports.input_source import SectorInputSource
from qtf.application.ports.repositories import ResearchRepository, RuntimeRepository
from qtf.contracts.errors import QtfDraftConflict, QtfRequestConflict, QtfRequestInvalid, QtfStateConflict
from qtf.contracts.research import ExperimentRevisionStatus
from qtf.contracts.runtime import InputPreflightPhase, InputPreflightRecord
from qtf.engine.canonical_hash import revision_content_hash
from qtf.modules.sector.input_contract import SectorInputRequest
from qtf.modules.sector.input_contract import SECTOR_L2_SOURCE_CONTRACT
from qtf.modules.sector.input_preflight import (
    evaluate_sector_input,
    required_source_history_days,
    resolve_parameter_matrix,
)
from qtf.modules.sector.plan_estimator import SOURCE_STATEMENT_TIMEOUT_MS
from qtf.modules.sector.validation_contract import (
    SECTOR_L2_VALIDATION_CONTRACT,
    validate_sector_validation_selection,
)
from qtf.engine.canonical_hash import canonical_json_hash


class InputPreflightService:
    def __init__(
        self,
        *,
        research_repository: ResearchRepository,
        runtime_repository: RuntimeRepository,
        input_source: SectorInputSource,
        key_factory: Callable[[], str] | None = None,
    ) -> None:
        self._research_repository = research_repository
        self._runtime_repository = runtime_repository
        self._input_source = input_source
        self._key_factory = key_factory or (lambda: f"qtf_preflight_{uuid4().hex}")

    def preview(
        self,
        *,
        research_key: str,
        request_key: str,
        draft_version: int,
        requested_start_date: date,
        requested_end_date: date,
    ) -> InputPreflightRecord:
        if not request_key.strip():
            raise QtfRequestInvalid("request_key is required")
        if requested_start_date > requested_end_date:
            raise QtfRequestInvalid("requested start date must not be after end date")
        bundle = self._research_repository.get_bundle_by_research_key(research_key)
        revision = bundle.revision
        if revision.status is not ExperimentRevisionStatus.DRAFT:
            raise QtfStateConflict("only DRAFT revisions can be previewed")
        if revision.draft_version != draft_version:
            raise QtfDraftConflict("draft version changed; reload before preflight")
        draft_hash = revision_content_hash(revision.content)
        expected_source_hash = canonical_json_hash(SECTOR_L2_SOURCE_CONTRACT)
        if revision.content.source_contract != SECTOR_L2_SOURCE_CONTRACT:
            raise QtfRequestInvalid("draft source contract does not match the registered template")

        existing = self._runtime_repository.find_preflight_by_request_key(request_key)
        if existing is not None:
            if (
                existing.revision_id != revision.id
                or existing.draft_hash != draft_hash
                or existing.requested_start_date != requested_start_date
                or existing.requested_end_date != requested_end_date
            ):
                raise QtfRequestConflict("request_key was already used for a different preflight")
            return existing

        # Fail before any source read when the parameter selection is incomplete or illegal.
        parameter_matrix = resolve_parameter_matrix(revision.content.effective_params)
        validation_gate_selection = _validation_gate_selection(revision.content.validation_spec)
        normalized_validation_selection = validate_sector_validation_selection(
            validation_gate_selection
        )
        history_trade_days = required_source_history_days(parameter_matrix) + int(
            normalized_validation_selection["warmup_probe_trade_days"]
        )
        snapshot = self._input_source.read(
            SectorInputRequest(
                start_date=requested_start_date,
                end_date=requested_end_date,
                history_trade_days=history_trade_days,
                future_trade_days=SECTOR_L2_VALIDATION_CONTRACT.label_tail_trade_days,
                statement_timeout_ms=SOURCE_STATEMENT_TIMEOUT_MS,
            )
        )
        if snapshot.source_contract_hash != expected_source_hash:
            raise QtfRequestInvalid("input source contract does not match the registered template")
        evaluation = evaluate_sector_input(
            snapshot,
            draft_effective_params=revision.content.effective_params,
            success_definition=revision.content.success_definition,
            validation_gate_selection=normalized_validation_selection,
            requested_start_date=requested_start_date,
            requested_end_date=requested_end_date,
        )
        plan_payload = {} if evaluation.plan is None else _jsonable(evaluation.plan.as_dict())
        return self._runtime_repository.create_preflight(
            preflight_key=self._key_factory(),
            request_key=request_key.strip(),
            revision_id=revision.id,
            draft_hash=draft_hash,
            phase=InputPreflightPhase.DRAFT_PREVIEW.value,
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
            plan_estimate=plan_payload,
            content_hash=snapshot.content_hash,
            completed_at=snapshot.as_of,
            issues=evaluation.issues,
        )


def _jsonable(value: object) -> object:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _validation_gate_selection(validation_spec: Mapping[str, object]) -> Mapping[str, object]:
    if set(validation_spec) != {"validation_gate_config"}:
        raise QtfRequestInvalid(
            "draft validation spec must contain exactly validation_gate_config"
        )
    value = validation_spec["validation_gate_config"]
    if not isinstance(value, Mapping):
        raise QtfRequestInvalid("validationGateConfig must be an object")
    return value
