"""Generic next-phase versus invalidation outcome labeling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Mapping

from .identities import canonical_datetime, stable_hash
from .scenarios import ScenarioSnapshot


ANALYSIS_MODULE_KEY = "wave_scenario_progression"
MODULE_VERSION = "WAVE_SCENARIO_PROGRESSION_V1"
ELIGIBILITY_CONTRACT_VERSION = "PROGRESSION_ELIGIBILITY_V1"
OUTCOME_SPACE_VERSION = "PROGRESSION_OUTCOME_SPACE_V1"
LABEL_VERSION = "PROGRESSION_LABEL_V1"
FEATURE_CONTRACT_VERSION = "PROGRESSION_FEATURES_V1"
CALIBRATION_CONTRACT_VERSION = "PROGRESSION_CALIBRATION_V1"
PRIMARY_HORIZON_BARS = 20
SENSITIVITY_HORIZON_BARS = (10, 40)
TIE_POLICY = "INVALIDATION_FIRST"


class ProgressionOutcome(str, Enum):
    NEXT_PHASE_CONFIRMED = "next_phase_confirmed"
    SCENARIO_INVALIDATED = "scenario_invalidated"
    UNRESOLVED = "unresolved"


class LabelingStatus(str, Enum):
    MATURED = "MATURED"
    NOT_MATURED = "NOT_MATURED"


@dataclass(frozen=True, slots=True)
class AnalysisModuleSnapshot:
    analysis_module_key: str
    module_version: str
    module_snapshot_id: str
    scenario_key: str
    scenario_lineage_key: str
    ts_code: str
    freq: str
    as_of: datetime
    decision_phase: str
    eligibility_contract_version: str
    outcome_space_version: str
    horizon_value: int
    horizon_unit: str
    label_version: str
    feature_contract_version: str
    calibration_contract_version: str
    scenario_model_version: str
    scenario_score_profile_version: str
    scenario_data_snapshot_id: str
    feature_payload: tuple[tuple[str, object], ...]


@dataclass(frozen=True, slots=True)
class ProgressionObservation:
    bar_end_at: datetime
    next_phase_confirmed: bool = False
    scenario_invalidated: bool = False
    trigger_rule_key: str | None = None


@dataclass(frozen=True, slots=True)
class OutcomeLabel:
    event_key: str
    module_snapshot_id: str
    scenario_key: str
    scenario_lineage_key: str
    ts_code: str
    freq: str
    decision_as_of: datetime
    decision_phase: str
    outcome_key: ProgressionOutcome
    outcome_at: datetime
    label_matured_at: datetime
    horizon_value: int
    horizon_unit: str
    horizon_end_at: datetime
    outcome_space_version: str
    label_version: str
    scenario_model_version: str
    data_snapshot_id: str
    trigger_rule_key: str | None
    tie_policy: str
    label_diagnostics: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LabelingResult:
    status: LabelingStatus
    label: OutcomeLabel | None
    observed_bar_count: int


def _assert_online_payload(payload: Mapping[str, object]) -> None:
    forbidden = {"outcome_key", "outcome_at"}

    def visit(value: object) -> None:
        if isinstance(value, Mapping):
            present = forbidden.intersection(str(key).lower() for key in value)
            if present:
                raise ValueError(
                    f"online feature payload leaks outcome fields: {sorted(present)}"
                )
            for item in value.values():
                visit(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item)

    visit(payload)


def build_module_snapshot(
    scenario: ScenarioSnapshot,
    *,
    feature_payload: Mapping[str, object] | None = None,
    horizon_bars: int = PRIMARY_HORIZON_BARS,
) -> AnalysisModuleSnapshot:
    if horizon_bars <= 0:
        raise ValueError("horizon must be positive")
    payload = dict(feature_payload or {})
    _assert_online_payload(payload)
    module_snapshot_id = stable_hash(
        "module-snapshot/v1",
        ANALYSIS_MODULE_KEY,
        MODULE_VERSION,
        scenario.scenario_key,
        canonical_datetime(scenario.as_of),
        str(horizon_bars),
    )
    return AnalysisModuleSnapshot(
        analysis_module_key=ANALYSIS_MODULE_KEY,
        module_version=MODULE_VERSION,
        module_snapshot_id=module_snapshot_id,
        scenario_key=scenario.scenario_key,
        scenario_lineage_key=scenario.scenario_lineage_key,
        ts_code=scenario.ts_code,
        freq=scenario.freq,
        as_of=scenario.as_of,
        decision_phase=scenario.current_phase,
        eligibility_contract_version=ELIGIBILITY_CONTRACT_VERSION,
        outcome_space_version=OUTCOME_SPACE_VERSION,
        horizon_value=horizon_bars,
        horizon_unit="BAR",
        label_version=LABEL_VERSION,
        feature_contract_version=FEATURE_CONTRACT_VERSION,
        calibration_contract_version=CALIBRATION_CONTRACT_VERSION,
        scenario_model_version=scenario.model_version,
        scenario_score_profile_version=scenario.score_profile_version,
        scenario_data_snapshot_id=scenario.data_snapshot_id,
        feature_payload=tuple(sorted(payload.items())),
    )


def label_progression(
    module_snapshot: AnalysisModuleSnapshot,
    future_observations: tuple[ProgressionObservation, ...]
    | list[ProgressionObservation],
) -> LabelingResult:
    observations = tuple(future_observations)
    if any(item.bar_end_at <= module_snapshot.as_of for item in observations):
        raise ValueError("label observation must begin after decision as_of")
    if any(
        current.bar_end_at <= previous.bar_end_at
        for previous, current in zip(observations, observations[1:])
    ):
        raise ValueError("label observations must be strictly ordered")
    window = observations[: module_snapshot.horizon_value]
    if len(window) < module_snapshot.horizon_value:
        return LabelingResult(LabelingStatus.NOT_MATURED, None, len(window))
    event_key = stable_hash(
        "progression-event/v1",
        module_snapshot.analysis_module_key,
        module_snapshot.module_snapshot_id,
        module_snapshot.scenario_key,
        canonical_datetime(module_snapshot.as_of),
    )
    for observation in window:
        if (
            not observation.next_phase_confirmed
            and not observation.scenario_invalidated
        ):
            continue
        tie = observation.next_phase_confirmed and observation.scenario_invalidated
        outcome = (
            ProgressionOutcome.SCENARIO_INVALIDATED
            if observation.scenario_invalidated
            else ProgressionOutcome.NEXT_PHASE_CONFIRMED
        )
        label = OutcomeLabel(
            event_key=event_key,
            module_snapshot_id=module_snapshot.module_snapshot_id,
            scenario_key=module_snapshot.scenario_key,
            scenario_lineage_key=module_snapshot.scenario_lineage_key,
            ts_code=module_snapshot.ts_code,
            freq=module_snapshot.freq,
            decision_as_of=module_snapshot.as_of,
            decision_phase=module_snapshot.decision_phase,
            outcome_key=outcome,
            outcome_at=observation.bar_end_at,
            label_matured_at=observation.bar_end_at,
            horizon_value=module_snapshot.horizon_value,
            horizon_unit="BAR",
            horizon_end_at=window[-1].bar_end_at,
            outcome_space_version=module_snapshot.outcome_space_version,
            label_version=module_snapshot.label_version,
            scenario_model_version=module_snapshot.scenario_model_version,
            data_snapshot_id=module_snapshot.scenario_data_snapshot_id,
            trigger_rule_key=observation.trigger_rule_key,
            tie_policy=TIE_POLICY,
            label_diagnostics=("SAME_BAR_TIE_INVALIDATION_FIRST",) if tie else (),
        )
        return LabelingResult(LabelingStatus.MATURED, label, len(window))
    horizon_end = window[-1].bar_end_at
    label = OutcomeLabel(
        event_key=event_key,
        module_snapshot_id=module_snapshot.module_snapshot_id,
        scenario_key=module_snapshot.scenario_key,
        scenario_lineage_key=module_snapshot.scenario_lineage_key,
        ts_code=module_snapshot.ts_code,
        freq=module_snapshot.freq,
        decision_as_of=module_snapshot.as_of,
        decision_phase=module_snapshot.decision_phase,
        outcome_key=ProgressionOutcome.UNRESOLVED,
        outcome_at=horizon_end,
        label_matured_at=horizon_end,
        horizon_value=module_snapshot.horizon_value,
        horizon_unit="BAR",
        horizon_end_at=horizon_end,
        outcome_space_version=module_snapshot.outcome_space_version,
        label_version=module_snapshot.label_version,
        scenario_model_version=module_snapshot.scenario_model_version,
        data_snapshot_id=module_snapshot.scenario_data_snapshot_id,
        trigger_rule_key=None,
        tie_policy=TIE_POLICY,
        label_diagnostics=("HORIZON_EXHAUSTED_WITHOUT_EVENT",),
    )
    return LabelingResult(LabelingStatus.MATURED, label, len(window))
