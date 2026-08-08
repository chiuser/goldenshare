"""Multi-scenario generation, deterministic ranking, and lineage tracking."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

from .grammar import (
    GenerationStatus,
    GrammarProfileKey,
    RuleEvaluation,
    ScenarioStatus,
    evaluate_grammar,
    resolve_grammar_profile,
)
from .identities import stable_hash
from .pivot import MODEL_VERSION, PivotConfirmation
from .profiles import DegreeProfile, DetectorProfile
from .scoring import FeatureEvaluation, SCORE_PROFILE_V1, ScoreProfile, score_scenario
from .swings import ConfirmedSwing, FormingLeg


ENGINE_KEY = "CAUSAL_MULTI_SCENARIO_WAVE_ENGINE"
ENGINE_VERSION = "INDEX_WAVE_ENGINE_V1"


@dataclass(frozen=True, slots=True)
class ScenarioSnapshot:
    model_version: str
    score_profile_version: str
    data_snapshot_id: str
    ts_code: str
    freq: str
    as_of: datetime
    degree_key: str
    scenario_key: str
    scenario_lineage_key: str
    parent_scenario_key: str | None
    scenario_type: str
    direction: str
    ordered_pivot_keys: tuple[str, ...]
    current_phase: str
    confirmed_wave_count: int
    scenario_status: ScenarioStatus
    status_changed_at: datetime
    valid_from_as_of: datetime
    rank: int | None
    ranking_score: Decimal | None
    heuristic_score: Decimal | None
    score_coverage: Decimal
    score_spread: Decimal | None
    hard_evaluations: tuple[RuleEvaluation, ...]
    soft_evaluations: tuple[FeatureEvaluation, ...]
    uses_provisional: bool
    forming_leg: FormingLeg | None
    invalidation_price: Decimal | None
    invalidation_rule_key: str | None
    detector_profile_key: str
    grammar_profile_key: str
    engine_key: str
    engine_version: str
    bar_visible_through: datetime
    context_status: str


@dataclass(frozen=True, slots=True)
class ScenarioGenerationResult:
    generation_status: GenerationStatus
    snapshots: tuple[ScenarioSnapshot, ...]
    terminal_snapshots: tuple[ScenarioSnapshot, ...]
    candidate_count: int
    pruned_count: int
    diagnostics: tuple[str, ...]


class ScenarioLifecycleTracker:
    """Keep immutable snapshots and explicitly feed prior state into evolution."""

    def __init__(self, *, retain_history: bool = False) -> None:
        self._latest: tuple[ScenarioSnapshot, ...] = ()
        self._retain_history = retain_history
        self._history: list[ScenarioSnapshot] = []
        self._last_pivot_keys: tuple[str, ...] | None = None
        self._last_result: ScenarioGenerationResult | None = None

    @property
    def history(self) -> tuple[ScenarioSnapshot, ...]:
        return tuple(self._history)

    def generate(
        self,
        pivots: tuple[PivotConfirmation, ...],
        *,
        degree: DegreeProfile,
        detector: DetectorProfile,
        as_of: datetime,
        bar_visible_through: datetime,
        swings: tuple[ConfirmedSwing, ...] | None = None,
    ) -> ScenarioGenerationResult:
        pivot_keys = tuple(pivot.pivot_key for pivot in pivots)
        if self._last_result is not None and pivot_keys == self._last_pivot_keys:
            snapshots = tuple(
                replace(
                    snapshot,
                    as_of=as_of,
                    bar_visible_through=bar_visible_through,
                )
                for snapshot in self._last_result.snapshots
            )
            result = ScenarioGenerationResult(
                generation_status=self._last_result.generation_status,
                snapshots=snapshots,
                terminal_snapshots=(),
                candidate_count=self._last_result.candidate_count,
                pruned_count=self._last_result.pruned_count,
                diagnostics=tuple(
                    item
                    for item in self._last_result.diagnostics
                    if item != "UNCHANGED_CONFIRMED_PIVOTS_REUSED"
                )
                + ("UNCHANGED_CONFIRMED_PIVOTS_REUSED",),
            )
            self._latest = snapshots
            self._last_result = result
            if self._retain_history:
                self._history.extend(snapshots)
            return result
        result = generate_scenarios(
            pivots,
            degree=degree,
            detector=detector,
            as_of=as_of,
            bar_visible_through=bar_visible_through,
            swings=swings,
            previous_snapshots=self._latest,
        )
        self._latest = result.snapshots + result.terminal_snapshots
        self._last_pivot_keys = pivot_keys
        self._last_result = result
        if self._retain_history:
            self._history.extend(self._latest)
        return result


def _scenario_identity(
    pivots: tuple[PivotConfirmation, ...],
    degree: DegreeProfile,
    grammar: GrammarProfileKey,
    scenario_type: str,
    direction: str,
) -> tuple[str, str]:
    first = pivots[0]
    scenario_key = stable_hash(
        "scenario/v1",
        first.ts_code,
        first.freq,
        degree.degree_key,
        grammar.value,
        scenario_type,
        direction,
        *[pivot.pivot_key for pivot in pivots],
    )
    lineage_key = stable_hash(
        "scenario-lineage/v1",
        first.ts_code,
        first.freq,
        degree.degree_key,
        grammar.value,
        scenario_type,
        direction,
        first.pivot_key,
    )
    return scenario_key, lineage_key


def _matching_previous(
    previous: tuple[ScenarioSnapshot, ...],
    lineage_key: str,
    ordered_keys: tuple[str, ...],
) -> tuple[ScenarioSnapshot | None, ScenarioSnapshot | None]:
    same_lineage = tuple(
        snapshot
        for snapshot in previous
        if snapshot.scenario_lineage_key == lineage_key
    )
    exact = next(
        (
            snapshot
            for snapshot in reversed(same_lineage)
            if snapshot.ordered_pivot_keys == ordered_keys
        ),
        None,
    )
    parents = tuple(
        snapshot
        for snapshot in same_lineage
        if len(snapshot.ordered_pivot_keys) < len(ordered_keys)
        and ordered_keys[: len(snapshot.ordered_pivot_keys)]
        == snapshot.ordered_pivot_keys
    )
    parent = max(parents, key=lambda item: len(item.ordered_pivot_keys), default=None)
    return exact, parent


def _validate_scenario_pivots(
    pivots: tuple[PivotConfirmation, ...],
    *,
    degree: DegreeProfile,
    detector: DetectorProfile,
    as_of: datetime,
    bar_visible_through: datetime,
) -> None:
    if len(pivots) < 2:
        raise ValueError("a scenario requires at least two confirmed pivots")
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("scenario as_of must be timezone-aware")
    if bar_visible_through > as_of:
        raise ValueError("bar_visible_through cannot exceed as_of")
    first = pivots[0]
    identity = (
        first.model_version,
        first.data_snapshot_id,
        first.ts_code,
        first.freq,
        first.degree_key,
        first.detector_profile_key,
        first.source_asset_key,
    )
    if first.degree_key != degree.degree_key:
        raise ValueError("pivot degree does not match scenario degree")
    if first.detector_profile_key != detector.detector_profile_key:
        raise ValueError("pivot detector does not match scenario detector")
    seen_keys: set[str] = set()
    previous: PivotConfirmation | None = None
    for pivot in pivots:
        current_identity = (
            pivot.model_version,
            pivot.data_snapshot_id,
            pivot.ts_code,
            pivot.freq,
            pivot.degree_key,
            pivot.detector_profile_key,
            pivot.source_asset_key,
        )
        if current_identity != identity:
            raise ValueError("scenario pivots mix model, source, or run identity")
        if pivot.pivot_key in seen_keys:
            raise ValueError("scenario pivots contain a duplicate key")
        if not pivot.extreme_price.is_finite() or pivot.extreme_price <= 0:
            raise ValueError("scenario pivot price must be finite and positive")
        if not (pivot.extreme_at <= pivot.confirmed_at <= as_of):
            raise ValueError("scenario pivot violates extreme/confirmation/as_of order")
        if previous is not None:
            if previous.pivot_type is pivot.pivot_type:
                raise ValueError("scenario pivot types must alternate")
            if previous.extreme_at >= pivot.extreme_at:
                raise ValueError("scenario extreme times must be strictly increasing")
            if previous.confirmed_at >= pivot.confirmed_at:
                raise ValueError(
                    "scenario confirmation times must be strictly increasing"
                )
        seen_keys.add(pivot.pivot_key)
        previous = pivot
    if bar_visible_through < pivots[-1].confirmed_at:
        raise ValueError("bar visibility cannot precede the latest confirmed pivot")


def build_scenario_snapshot(
    pivots: tuple[PivotConfirmation, ...],
    *,
    grammar_profile_key: GrammarProfileKey,
    degree: DegreeProfile,
    detector: DetectorProfile,
    as_of: datetime,
    bar_visible_through: datetime,
    swings: tuple[ConfirmedSwing, ...] | None = None,
    previous_snapshots: tuple[ScenarioSnapshot, ...] = (),
    score_profile: ScoreProfile = SCORE_PROFILE_V1,
    forming_leg: FormingLeg | None = None,
) -> ScenarioSnapshot:
    _validate_scenario_pivots(
        pivots,
        degree=degree,
        detector=detector,
        as_of=as_of,
        bar_visible_through=bar_visible_through,
    )
    evaluation = evaluate_grammar(pivots, grammar_profile_key)
    score = score_scenario(
        grammar_profile_key, pivots, swings=swings, profile=score_profile
    )
    ordered_keys = tuple(pivot.pivot_key for pivot in pivots)
    scenario_key, lineage_key = _scenario_identity(
        pivots,
        degree,
        grammar_profile_key,
        evaluation.scenario_type,
        evaluation.direction.value,
    )
    exact, parent = _matching_previous(previous_snapshots, lineage_key, ordered_keys)
    status_changed_at = (
        exact.status_changed_at
        if exact is not None and exact.scenario_status is evaluation.status
        else as_of
    )
    valid_from_as_of = exact.valid_from_as_of if exact is not None else as_of
    return ScenarioSnapshot(
        model_version=MODEL_VERSION,
        score_profile_version=score_profile.score_profile_version,
        data_snapshot_id=pivots[0].data_snapshot_id,
        ts_code=pivots[0].ts_code,
        freq=pivots[0].freq,
        as_of=as_of,
        degree_key=degree.degree_key,
        scenario_key=scenario_key,
        scenario_lineage_key=lineage_key,
        parent_scenario_key=parent.scenario_key if parent is not None else None,
        scenario_type=evaluation.scenario_type,
        direction=evaluation.direction.value,
        ordered_pivot_keys=ordered_keys,
        current_phase=evaluation.current_phase,
        confirmed_wave_count=evaluation.confirmed_wave_count,
        scenario_status=evaluation.status,
        status_changed_at=status_changed_at,
        valid_from_as_of=valid_from_as_of,
        rank=None,
        ranking_score=score.ranking_score,
        heuristic_score=score.heuristic_score,
        score_coverage=score.score_coverage,
        score_spread=None,
        hard_evaluations=evaluation.hard_evaluations,
        soft_evaluations=score.features,
        uses_provisional=forming_leg is not None,
        forming_leg=forming_leg,
        invalidation_price=(
            pivots[-1].extreme_price
            if evaluation.status is ScenarioStatus.INVALIDATED
            else None
        ),
        invalidation_rule_key=evaluation.invalidation_rule_key,
        detector_profile_key=detector.detector_profile_key,
        grammar_profile_key=grammar_profile_key.value,
        engine_key=ENGINE_KEY,
        engine_version=ENGINE_VERSION,
        bar_visible_through=bar_visible_through,
        context_status=evaluation.context_status,
    )


def _rank_key(snapshot: ScenarioSnapshot):
    missing = snapshot.ranking_score is None
    ranking = snapshot.ranking_score or Decimal(0)
    heuristic = snapshot.heuristic_score or Decimal(0)
    return (
        missing,
        -ranking,
        -heuristic,
        -snapshot.score_coverage,
        -snapshot.confirmed_wave_count,
        snapshot.scenario_key,
    )


def rank_scenarios(
    snapshots: tuple[ScenarioSnapshot, ...], max_scenarios: int
) -> tuple[tuple[ScenarioSnapshot, ...], int]:
    ranked = sorted(snapshots, key=_rank_key)
    retained = ranked[:max_scenarios]
    spread = None
    if len(retained) >= 2:
        first_score = retained[0].ranking_score
        second_score = retained[1].ranking_score
        if first_score is not None and second_score is not None:
            spread = first_score - second_score
    output = tuple(
        replace(snapshot, rank=index + 1, score_spread=spread)
        for index, snapshot in enumerate(retained)
    )
    return output, max(0, len(ranked) - len(retained))


def generate_scenarios(
    pivots: tuple[PivotConfirmation, ...],
    *,
    degree: DegreeProfile,
    detector: DetectorProfile,
    as_of: datetime,
    bar_visible_through: datetime,
    swings: tuple[ConfirmedSwing, ...] | None = None,
    previous_snapshots: tuple[ScenarioSnapshot, ...] = (),
    grammar_profile_keys: tuple[str | GrammarProfileKey, ...] = (
        GrammarProfileKey.IMPULSE_STANDARD_V1,
        GrammarProfileKey.CORRECTIVE_ZIGZAG_V1,
    ),
) -> ScenarioGenerationResult:
    resolved = tuple(
        grammar
        for value in grammar_profile_keys
        if (grammar := resolve_grammar_profile(value)) is not None
    )
    unsupported = len(grammar_profile_keys) - len(resolved)
    if not resolved or len(pivots) < 2:
        return ScenarioGenerationResult(
            GenerationStatus.UNSUPPORTED,
            (),
            (),
            0,
            0,
            ("NO_SUPPORTED_GRAMMAR_MATCH",),
        )

    recent_start = max(0, len(pivots) - degree.max_history_pivots)
    start_indices = tuple(range(recent_start, len(pivots) - 1))[
        -degree.max_start_candidates :
    ]
    swing_by_pair = (
        {(item.from_pivot_key, item.to_pivot_key): item for item in swings}
        if swings is not None
        else {}
    )
    candidates: list[ScenarioSnapshot] = []
    terminals: list[ScenarioSnapshot] = []
    for start_index in start_indices:
        for grammar in resolved:
            expected_pivots = (
                6 if grammar is GrammarProfileKey.IMPULSE_STANDARD_V1 else 4
            )
            structure = pivots[start_index:]
            if len(structure) > expected_pivots:
                continue
            structure_swings: tuple[ConfirmedSwing, ...] | None
            if swings is None:
                structure_swings = None
            else:
                selected: list[ConfirmedSwing] = []
                for left, right in zip(structure, structure[1:]):
                    item = swing_by_pair.get((left.pivot_key, right.pivot_key))
                    if item is None:
                        selected = []
                        break
                    selected.append(item)
                structure_swings = tuple(selected) if selected else None
            snapshot = build_scenario_snapshot(
                structure,
                grammar_profile_key=grammar,
                degree=degree,
                detector=detector,
                as_of=as_of,
                bar_visible_through=bar_visible_through,
                swings=structure_swings,
                previous_snapshots=previous_snapshots,
            )
            if snapshot.scenario_status is ScenarioStatus.INVALIDATED:
                terminals.append(snapshot)
            else:
                candidates.append(snapshot)
    ranked, pruned = rank_scenarios(tuple(candidates), degree.max_scenarios)
    diagnostics = [
        f"CANDIDATES={len(candidates)}",
        f"INVALIDATED_TERMINALS={len(terminals)}",
        f"PRUNED={pruned}",
    ]
    if unsupported:
        diagnostics.append(f"UNSUPPORTED_GRAMMARS={unsupported}")
    status = (
        GenerationStatus.SUPPORTED
        if candidates or terminals
        else GenerationStatus.UNSUPPORTED
    )
    return ScenarioGenerationResult(
        status,
        ranked,
        tuple(terminals),
        len(candidates) + len(terminals),
        pruned,
        tuple(diagnostics),
    )


def terminal_snapshot(
    snapshot: ScenarioSnapshot,
    *,
    as_of: datetime,
    status: ScenarioStatus,
    rule_key: str,
    invalidation_price: Decimal | None = None,
) -> ScenarioSnapshot:
    if status not in {ScenarioStatus.INVALIDATED, ScenarioStatus.SUPERSEDED}:
        raise ValueError(
            "terminal lifecycle transition must be invalidated or superseded"
        )
    return replace(
        snapshot,
        as_of=as_of,
        scenario_status=status,
        status_changed_at=as_of,
        invalidation_rule_key=rule_key,
        invalidation_price=invalidation_price,
        rank=None,
        score_spread=None,
    )


def assert_output_schema_is_research_only(
    field_names: tuple[str, ...] | list[str],
) -> None:
    forbidden = {"buy", "sell", "position", "trade_action"}
    violations = forbidden.intersection(name.lower() for name in field_names)
    if violations:
        raise ValueError(
            f"generic output contains trading fields: {sorted(violations)}"
        )
