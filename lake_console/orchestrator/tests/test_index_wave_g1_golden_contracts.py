from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from orchestrator.analysis.index_wave.bars import (
    CanonicalBar,
    ContinuityStatus,
    InputContractError,
    adapt_canonical_rows,
    validate_canonical_bars,
)
from orchestrator.analysis.index_wave.calibration import (
    OUTCOME_KEYS,
    CalibrationRecord,
    CalibrationStatus,
    build_probability_snapshot,
    evaluate_calibration_gate,
    validate_temporal_split,
    validate_probability_simplex,
)
from orchestrator.analysis.index_wave.grammar import (
    GenerationStatus,
    GrammarProfileKey,
    RuleStatus,
    ScenarioStatus,
    evaluate_grammar,
)
from orchestrator.analysis.index_wave.pivot import (
    MODEL_VERSION,
    DetectorState,
    PivotConfirmation,
    PivotType,
    detect_pivots,
    wilder_atr,
)
from orchestrator.analysis.index_wave.profiles import (
    BASE_DEGREE_PROFILE,
    CAUSAL_ATR_PROFILE,
    DegreeProfile,
    DetectorProfile,
    validate_generic_profile_payload,
)
from orchestrator.analysis.index_wave.progression import (
    AnalysisModuleSnapshot,
    LabelingStatus,
    ProgressionObservation,
    ProgressionOutcome,
    build_module_snapshot,
    label_progression,
)
from orchestrator.analysis.index_wave.replay import (
    IncrementalWaveReplay,
    replay_wave,
    validate_context_visibility,
)
from orchestrator.analysis.index_wave.scenarios import (
    ScenarioSnapshot,
    assert_output_schema_is_research_only,
    build_scenario_snapshot,
    generate_scenarios,
    rank_scenarios,
)
from orchestrator.analysis.index_wave.scoring import (
    IMPULSE_WEIGHTS_V1,
    RATIO_BANDS_V1,
    SCORE_PROFILE_V1,
    FeatureStatus,
    RatioBand,
    proximity,
    ratio_component,
    score_scenario,
)
from orchestrator.analysis.index_wave.swings import (
    ConfirmedSwing,
    Direction,
    build_forming_leg,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
BASE_TIME = datetime(2024, 1, 2, 15, 0, tzinfo=SHANGHAI)


def make_bar(
    index: int,
    *,
    high: Decimal | int | float | str,
    low: Decimal | int | float | str,
    close: Decimal | int | float | str,
    open_: Decimal | int | float | str | None = None,
    freq: str = "1d",
    step: timedelta = timedelta(days=1),
    snapshot: str = "snapshot-v1",
) -> CanonicalBar:
    bar_end_at = BASE_TIME + index * step
    return CanonicalBar(
        ts_code="000001.SH",
        freq=freq,
        trade_date=bar_end_at.date(),
        bar_end_at=bar_end_at,
        open=close if open_ is None else open_,
        high=high,
        low=low,
        close=close,
        vol=0,
        amount=0,
        source_asset_key="silver/market/index_daily"
        if freq == "1d"
        else "silver/market/major_index_mins",
        source_partition=bar_end_at.date().isoformat(),
        source_contract_version="canonical-test-v1",
        data_snapshot_id=snapshot,
    )


def fixed_profile_and_degree(
    threshold: Decimal | int | float | str = 5,
) -> tuple[DetectorProfile, DegreeProfile]:
    profile = DetectorProfile.absolute_test(threshold)
    degree = DegreeProfile(
        degree_key="BASE_ABSOLUTE_TEST_V1",
        degree_version="DEGREE_PROFILE_TEST_V1",
        detector_profile_key=profile.detector_profile_key,
        grammar_profile_version="GRAMMAR_PROFILE_V1",
    )
    return profile, degree


def make_pivots(
    prices: list[Decimal | int | float | str],
    *,
    first_type: PivotType,
    freq: str = "1d",
    snapshot: str = "scenario-snapshot-v1",
) -> tuple[PivotConfirmation, ...]:
    pivots: list[PivotConfirmation] = []
    for index, raw_price in enumerate(prices):
        price = Decimal(str(raw_price))
        pivot_type = (
            first_type
            if index % 2 == 0
            else PivotType.HIGH
            if first_type is PivotType.LOW
            else PivotType.LOW
        )
        extreme_at = BASE_TIME + timedelta(days=index * 2)
        confirmed_at = extreme_at + timedelta(days=1)
        pivots.append(
            PivotConfirmation(
                model_version=MODEL_VERSION,
                data_snapshot_id=snapshot,
                ts_code="000001.SH",
                freq=freq,
                degree_key="BASE_ABSOLUTE_TEST_V1",
                pivot_key=f"pivot-{freq}-{index}-{price}",
                pivot_type=pivot_type,
                extreme_at=extreme_at,
                extreme_trade_date=extreme_at.date(),
                extreme_price=price,
                confirmed_at=confirmed_at,
                confirmation_trade_date=confirmed_at.date(),
                confirmation_close=price,
                threshold_at_extreme=Decimal(5),
                detector_profile_key="ABSOLUTE_REVERSAL_TEST_5_V1",
                extreme_bar_key=f"bar-extreme-{freq}-{index}",
                confirmation_bar_key=f"bar-confirm-{freq}-{index}",
                source_asset_key="fixture",
                extreme_source_partition=extreme_at.date().isoformat(),
                confirmation_source_partition=confirmed_at.date().isoformat(),
                created_at=confirmed_at,
            )
        )
    return tuple(pivots)


def make_swings(
    pivots: tuple[PivotConfirmation, ...], durations: list[int]
) -> tuple[ConfirmedSwing, ...]:
    assert len(durations) == len(pivots) - 1
    output: list[ConfirmedSwing] = []
    for index, (start, end) in enumerate(zip(pivots, pivots[1:])):
        direction = (
            Direction.UP if start.pivot_type is PivotType.LOW else Direction.DOWN
        )
        output.append(
            ConfirmedSwing(
                swing_key=f"swing-{index}",
                from_pivot_key=start.pivot_key,
                to_pivot_key=end.pivot_key,
                direction=direction,
                start_at=start.extreme_at,
                end_at=end.extreme_at,
                available_at=end.confirmed_at,
                start_price=start.extreme_price,
                end_price=end.extreme_price,
                absolute_change=end.extreme_price - start.extreme_price,
                return_ratio=end.extreme_price / start.extreme_price - Decimal(1),
                duration_bars=durations[index],
                confirmation_delay_bars=1,
            )
        )
    return tuple(output)


def make_scenario(pivots: tuple[PivotConfirmation, ...], grammar: GrammarProfileKey):
    profile, degree = fixed_profile_and_degree()
    return build_scenario_snapshot(
        pivots,
        grammar_profile_key=grammar,
        degree=degree,
        detector=profile,
        as_of=pivots[-1].confirmed_at,
        bar_visible_through=pivots[-1].confirmed_at,
    )


def detector_fixture_bars(*, freq: str = "1d") -> tuple[CanonicalBar, ...]:
    step = timedelta(days=1) if freq == "1d" else timedelta(minutes=30)
    return (
        make_bar(0, high=105, low=100, close=105, freq=freq, step=step),
        make_bar(1, high=110, low=106, close=109, freq=freq, step=step),
        make_bar(2, high=110, low=104, close=105, freq=freq, step=step),
        make_bar(3, high=106, low=101, close=102, freq=freq, step=step),
        make_bar(4, high=106, low=100, close=105, freq=freq, step=step),
        make_bar(5, high=112, low=106, close=111, freq=freq, step=step),
        make_bar(6, high=112, low=106, close=107, freq=freq, step=step),
    )


def test_f01_wilder_atr_seed_and_recursive_values_are_literal() -> None:
    bars = tuple(
        make_bar(
            index,
            high=Decimal(100) + Decimal(true_range) / 2,
            low=Decimal(100) - Decimal(true_range) / 2,
            close=100,
        )
        for index, true_range in enumerate(range(1, 17))
    )

    values = wilder_atr(bars, 14)

    seed = sum(map(Decimal, range(1, 15))) / Decimal(14)
    next_value = (seed * Decimal(13) + Decimal(15)) / Decimal(14)
    final_value = (next_value * Decimal(13) + Decimal(16)) / Decimal(14)
    assert values[:13] == (None,) * 13
    assert values[13] == seed == Decimal("7.5")
    assert values[14] == next_value
    assert values[15] == final_value


def test_f02_fixed_five_point_reversal_of_four_does_not_confirm_high() -> None:
    profile, degree = fixed_profile_and_degree(5)
    bars = (make_bar(0, high=108, low=100, close=104),)

    result = detect_pivots(bars, profile=profile, degree=degree)

    assert result.confirmations == ()
    assert result.state is DetectorState.UNDEFINED


def test_f03_fixed_five_point_reversal_confirms_original_high() -> None:
    profile, degree = fixed_profile_and_degree(5)
    bars = (
        make_bar(0, high=108, low=100, close=104),
        make_bar(1, high=107, low=102, close=103),
    )

    result = detect_pivots(bars, profile=profile, degree=degree)

    assert len(result.confirmations) == 1
    pivot = result.confirmations[0]
    assert pivot.pivot_type is PivotType.HIGH
    assert pivot.extreme_price == Decimal(108)
    assert pivot.extreme_at == bars[0].bar_end_at
    assert pivot.confirmed_at == bars[1].bar_end_at


def test_f04_undefined_dual_confirmation_waits_for_unambiguous_bar() -> None:
    profile, degree = fixed_profile_and_degree(5)
    bars = (make_bar(0, high=110, low=100, close=105),)

    result = detect_pivots(bars, profile=profile, degree=degree)

    assert result.confirmations == ()
    assert result.state is DetectorState.UNDEFINED
    assert result.candidate_high is not None
    assert result.candidate_low is not None


def test_f05_equal_high_keeps_earlier_extreme_and_key() -> None:
    profile, degree = fixed_profile_and_degree(5)
    bars = (
        make_bar(0, high=108, low=104, close=106),
        make_bar(1, high=108, low=105, close=106),
        make_bar(2, high=107, low=102, close=103),
    )

    result = detect_pivots(bars, profile=profile, degree=degree)

    assert len(result.confirmations) == 1
    assert result.confirmations[0].extreme_at == bars[0].bar_end_at
    assert result.confirmations[0].extreme_bar_key == bars[0].bar_key


def test_f06_confirmation_bar_low_is_not_reused_by_next_bar_reset() -> None:
    profile, degree = fixed_profile_and_degree(5)
    confirmation_prefix = (
        make_bar(0, high=105, low=100, close=105),
        make_bar(1, high=110, low=106, close=109),
        make_bar(2, high=110, low=90, close=105),
    )

    at_confirmation = detect_pivots(confirmation_prefix, profile=profile, degree=degree)
    after_next_bar = detect_pivots(
        confirmation_prefix + (make_bar(3, high=108, low=104, close=105),),
        profile=profile,
        degree=degree,
    )

    assert [item.pivot_type for item in at_confirmation.confirmations] == [
        PivotType.LOW,
        PivotType.HIGH,
    ]
    assert at_confirmation.state is DetectorState.DOWN
    assert at_confirmation.candidate_low is None
    assert after_next_bar.candidate_low is not None
    assert after_next_bar.candidate_low.extreme_price == Decimal(104)
    assert after_next_bar.candidate_low.extreme_price != Decimal(90)


def test_f07_exact_threshold_uses_greater_than_or_equal() -> None:
    profile, degree = fixed_profile_and_degree(5)
    bars = (
        make_bar(0, high=108, low=100, close=104),
        make_bar(1, high=107, low=102, close=103),
    )

    result = detect_pivots(bars, profile=profile, degree=degree)

    assert result.confirmations[0].extreme_price - bars[1].close == Decimal(5)
    assert result.confirmations[0].pivot_type is PivotType.HIGH


@pytest.mark.parametrize(
    ("bars", "reason_code"),
    [
        (
            (
                make_bar(0, high=105, low=100, close=103),
                make_bar(0, high=106, low=101, close=104),
            ),
            "BAR_SEQUENCE_DUPLICATE",
        ),
        (
            (
                make_bar(1, high=106, low=101, close=104),
                make_bar(0, high=105, low=100, close=103),
            ),
            "BAR_SEQUENCE_OUT_OF_ORDER",
        ),
        ((make_bar(0, high=5, low=0, close=3),), "BAR_PRICE_NON_POSITIVE"),
        ((make_bar(0, high=5, low=3, close=6),), "BAR_OHLC_ENVELOPE_INVALID"),
    ],
)
def test_f08_bad_canonical_input_fails_closed(
    bars: tuple[CanonicalBar, ...], reason_code: str
) -> None:
    with pytest.raises(InputContractError) as exc_info:
        validate_canonical_bars(bars)
    assert exc_info.value.reason_code == reason_code


def test_f09_up_impulse_completes_with_all_hard_rules_passed() -> None:
    pivots = make_pivots([100, 120, 110, 150, 130, 160], first_type=PivotType.LOW)

    evaluation = evaluate_grammar(pivots, GrammarProfileKey.IMPULSE_STANDARD_V1)

    assert evaluation.status is ScenarioStatus.COMPLETED
    assert evaluation.direction is Direction.UP
    assert all(rule.status is RuleStatus.PASS for rule in evaluation.hard_evaluations)


def test_f10_down_impulse_is_an_exact_mirror() -> None:
    pivots = make_pivots([200, 180, 190, 150, 175, 140], first_type=PivotType.HIGH)

    evaluation = evaluate_grammar(pivots, GrammarProfileKey.IMPULSE_STANDARD_V1)

    assert evaluation.status is ScenarioStatus.COMPLETED
    assert evaluation.direction is Direction.DOWN
    assert all(rule.status is RuleStatus.PASS for rule in evaluation.hard_evaluations)


def test_f11_wave2_beyond_origin_invalidates_immediately() -> None:
    pivots = make_pivots([100, 120, 99], first_type=PivotType.LOW)

    scenario = make_scenario(pivots, GrammarProfileKey.IMPULSE_STANDARD_V1)

    assert scenario.scenario_status is ScenarioStatus.INVALIDATED
    assert scenario.invalidation_rule_key == "WAVE2_NOT_BEYOND_ORIGIN"


def test_f12_wave3_shortest_is_not_yet_before_w5_then_fails() -> None:
    before_w5 = make_pivots([100, 120, 110, 128, 123], first_type=PivotType.LOW)
    after_w5 = make_pivots([100, 120, 110, 128, 123, 150], first_type=PivotType.LOW)

    before = evaluate_grammar(before_w5, GrammarProfileKey.IMPULSE_STANDARD_V1)
    after = evaluate_grammar(after_w5, GrammarProfileKey.IMPULSE_STANDARD_V1)
    before_rule = next(
        item
        for item in before.hard_evaluations
        if item.rule_key == "WAVE3_NOT_SHORTEST"
    )
    after_rule = next(
        item for item in after.hard_evaluations if item.rule_key == "WAVE3_NOT_SHORTEST"
    )

    assert before_rule.status is RuleStatus.NOT_YET_EVALUABLE
    assert after_rule.status is RuleStatus.FAIL
    assert after.status is ScenarioStatus.INVALIDATED


def test_f13_wave4_overlap_invalidates_standard_impulse() -> None:
    pivots = make_pivots([100, 120, 110, 150, 115], first_type=PivotType.LOW)

    scenario = make_scenario(pivots, GrammarProfileKey.IMPULSE_STANDARD_V1)

    assert scenario.scenario_status is ScenarioStatus.INVALIDATED
    assert scenario.invalidation_rule_key == "WAVE4_NO_WAVE1_OVERLAP"


def test_f14_down_zigzag_completes() -> None:
    pivots = make_pivots([160, 135, 150, 120], first_type=PivotType.HIGH)

    evaluation = evaluate_grammar(pivots, GrammarProfileKey.CORRECTIVE_ZIGZAG_V1)

    assert evaluation.status is ScenarioStatus.COMPLETED
    assert evaluation.direction is Direction.DOWN
    assert all(rule.status is RuleStatus.PASS for rule in evaluation.hard_evaluations)


def test_f15_zigzag_b_beyond_origin_invalidates() -> None:
    pivots = make_pivots([160, 135, 165], first_type=PivotType.HIGH)

    scenario = make_scenario(pivots, GrammarProfileKey.CORRECTIVE_ZIGZAG_V1)

    assert scenario.scenario_status is ScenarioStatus.INVALIDATED
    assert scenario.invalidation_rule_key == "B_NOT_BEYOND_ORIGIN"


def test_f16_partial_impulse_and_zigzag_alternative_are_both_retained() -> None:
    pivots = make_pivots([100, 120, 110, 130], first_type=PivotType.LOW)
    profile, degree = fixed_profile_and_degree()

    result = generate_scenarios(
        pivots,
        degree=degree,
        detector=profile,
        as_of=pivots[-1].confirmed_at,
        bar_visible_through=pivots[-1].confirmed_at,
    )
    full_structure = [
        item
        for item in result.snapshots
        if item.ordered_pivot_keys == tuple(p.pivot_key for p in pivots)
    ]

    assert result.generation_status is GenerationStatus.SUPPORTED
    assert {item.grammar_profile_key for item in full_structure} == {
        GrammarProfileKey.IMPULSE_STANDARD_V1.value,
        GrammarProfileKey.CORRECTIVE_ZIGZAG_V1.value,
    }


def test_f17_forming_extreme_moves_without_rewriting_confirmed_fact() -> None:
    profile, degree = fixed_profile_and_degree()
    first_prefix = (
        make_bar(0, high=105, low=100, close=105),
        make_bar(1, high=110, low=106, close=109),
    )
    second_prefix = first_prefix + (make_bar(2, high=112, low=107, close=111),)

    first = detect_pivots(first_prefix, profile=profile, degree=degree)
    second = detect_pivots(second_prefix, profile=profile, degree=degree)
    first_forming = build_forming_leg(first, first_prefix)
    second_forming = build_forming_leg(second, second_prefix)

    assert first.confirmations == second.confirmations
    assert first.confirmations[0].pivot_key == second.confirmations[0].pivot_key
    assert first_forming is not None and second_forming is not None
    assert first_forming.forming_extreme_price == Decimal(110)
    assert second_forming.forming_extreme_price == Decimal(112)
    assert first_forming.uses_provisional and second_forming.uses_provisional


def test_f18_later_replay_preserves_every_old_confirmation_identity_and_time() -> None:
    profile, degree = fixed_profile_and_degree()
    bars = detector_fixture_bars()
    generated_at = BASE_TIME + timedelta(days=100)

    at_t = detect_pivots(
        bars[:3], profile=profile, degree=degree, created_at=generated_at
    )
    at_t_plus_n = detect_pivots(
        bars, profile=profile, degree=degree, created_at=generated_at
    )

    assert at_t_plus_n.confirmations[: len(at_t.confirmations)] == at_t.confirmations
    assert [
        (item.pivot_key, item.extreme_at, item.confirmed_at)
        for item in at_t_plus_n.confirmations[: len(at_t.confirmations)]
    ] == [
        (item.pivot_key, item.extreme_at, item.confirmed_at)
        for item in at_t.confirmations
    ]


def test_f19_full_replay_and_incremental_append_are_identical() -> None:
    profile, degree = fixed_profile_and_degree()
    bars = detector_fixture_bars()
    generated_at = BASE_TIME + timedelta(days=100)

    full = replay_wave(
        bars,
        detector=profile,
        degree=degree,
        created_at=generated_at,
    )
    incremental = IncrementalWaveReplay(
        detector=profile, degree=degree, created_at=generated_at
    )
    incremental_final = None
    for bar in bars:
        incremental_final = incremental.append(bar)

    assert incremental_final is not None
    assert incremental_final == full.final
    assert (
        incremental_final.detection.confirmations == full.final.detection.confirmations
    )
    assert incremental_final.confirmed_scenarios == full.final.confirmed_scenarios


def test_f20_structure_extension_changes_exact_key_but_preserves_lineage() -> None:
    profile, degree = fixed_profile_and_degree()
    first_pivots = make_pivots([100, 120, 110], first_type=PivotType.LOW)
    extended_pivots = make_pivots([100, 120, 110, 150], first_type=PivotType.LOW)
    first = build_scenario_snapshot(
        first_pivots,
        grammar_profile_key=GrammarProfileKey.IMPULSE_STANDARD_V1,
        degree=degree,
        detector=profile,
        as_of=first_pivots[-1].confirmed_at,
        bar_visible_through=first_pivots[-1].confirmed_at,
    )
    extended = build_scenario_snapshot(
        extended_pivots,
        grammar_profile_key=GrammarProfileKey.IMPULSE_STANDARD_V1,
        degree=degree,
        detector=profile,
        as_of=extended_pivots[-1].confirmed_at,
        bar_visible_through=extended_pivots[-1].confirmed_at,
        previous_snapshots=(first,),
    )

    assert extended.scenario_key != first.scenario_key
    assert extended.scenario_lineage_key == first.scenario_lineage_key
    assert extended.parent_scenario_key == first.scenario_key
    assert first.parent_scenario_key is None


def test_f21_invalidated_main_is_terminal_and_backup_is_reranked_without_mutation() -> (
    None
):
    profile, degree = fixed_profile_and_degree()
    initial_pivots = make_pivots([100, 120], first_type=PivotType.LOW)
    first = generate_scenarios(
        initial_pivots,
        degree=degree,
        detector=profile,
        as_of=initial_pivots[-1].confirmed_at,
        bar_visible_through=initial_pivots[-1].confirmed_at,
    )
    old_main = next(
        item
        for item in first.snapshots
        if item.grammar_profile_key == GrammarProfileKey.IMPULSE_STANDARD_V1.value
        and item.ordered_pivot_keys[0] == initial_pivots[0].pivot_key
    )
    old_value = old_main
    invalidating_pivots = make_pivots([100, 120, 99], first_type=PivotType.LOW)
    current = generate_scenarios(
        invalidating_pivots,
        degree=degree,
        detector=profile,
        as_of=invalidating_pivots[-1].confirmed_at,
        bar_visible_through=invalidating_pivots[-1].confirmed_at,
        previous_snapshots=first.snapshots,
    )
    terminal = next(
        item
        for item in current.terminal_snapshots
        if item.scenario_lineage_key == old_main.scenario_lineage_key
        and item.grammar_profile_key == GrammarProfileKey.IMPULSE_STANDARD_V1.value
    )

    assert terminal.scenario_status is ScenarioStatus.INVALIDATED
    assert terminal.parent_scenario_key == old_main.scenario_key
    assert current.snapshots and current.snapshots[0].rank == 1
    assert (
        current.snapshots[0].ordered_pivot_keys[0] == invalidating_pivots[1].pivot_key
    )
    assert old_main == old_value
    assert old_main.scenario_status is ScenarioStatus.CANDIDATE


def test_f22_cross_period_context_cannot_read_a_not_yet_closed_daily_bar() -> None:
    decision_as_of = datetime(2024, 1, 2, 11, 30, tzinfo=SHANGHAI)
    daily_visible = datetime(2024, 1, 2, 15, 0, tzinfo=SHANGHAI)

    with pytest.raises(InputContractError) as exc_info:
        validate_context_visibility(
            decision_as_of=decision_as_of,
            visible_through_by_freq={"120min": decision_as_of, "1d": daily_visible},
        )

    assert exc_info.value.reason_code == "CROSS_PERIOD_FUTURE_CONTEXT"


def test_f23_no_event_by_twenty_bars_is_retained_as_unresolved() -> None:
    scenario = make_scenario(
        make_pivots([100, 120, 110], first_type=PivotType.LOW),
        GrammarProfileKey.IMPULSE_STANDARD_V1,
    )
    module = build_module_snapshot(scenario)
    observations = tuple(
        ProgressionObservation(module.as_of + timedelta(days=index + 1))
        for index in range(20)
    )

    result = label_progression(module, observations)

    assert result.status is LabelingStatus.MATURED
    assert result.label is not None
    assert result.label.outcome_key is ProgressionOutcome.UNRESOLVED
    assert result.label.horizon_value == 20
    assert result.label.horizon_unit == "BAR"


def test_f24_same_bar_progression_and_invalidation_uses_invalidation_first() -> None:
    scenario = make_scenario(
        make_pivots([100, 120, 110], first_type=PivotType.LOW),
        GrammarProfileKey.IMPULSE_STANDARD_V1,
    )
    module = build_module_snapshot(scenario)
    observation = ProgressionObservation(
        module.as_of + timedelta(days=1),
        next_phase_confirmed=True,
        scenario_invalidated=True,
        trigger_rule_key="SAME_BAR_AMBIGUITY",
    )

    observations = (observation,) + tuple(
        ProgressionObservation(module.as_of + timedelta(days=index + 1))
        for index in range(1, 20)
    )
    result = label_progression(module, observations)

    assert result.label is not None
    assert result.label.outcome_key is ProgressionOutcome.SCENARIO_INVALIDATED
    assert result.label.tie_policy == "INVALIDATION_FIRST"
    assert result.label.label_diagnostics == ("SAME_BAR_TIE_INVALIDATION_FIRST",)


def test_f25_three_outcome_probability_simplex_passes() -> None:
    probabilities = {
        ProgressionOutcome.NEXT_PHASE_CONFIRMED.value: Decimal("0.2"),
        ProgressionOutcome.SCENARIO_INVALIDATED.value: Decimal("0.3"),
        ProgressionOutcome.UNRESOLVED.value: Decimal("0.5"),
    }
    validate_probability_simplex(probabilities)
    scenario = make_scenario(
        make_pivots([100, 120, 110], first_type=PivotType.LOW),
        GrammarProfileKey.IMPULSE_STANDARD_V1,
    )
    module = build_module_snapshot(scenario)

    snapshot = build_probability_snapshot(
        module,
        calibration_status=CalibrationStatus.CALIBRATED,
        probabilities=probabilities,
        primary_outcome_key=ProgressionOutcome.UNRESOLVED.value,
        outcome_intervals={key: (Decimal(0), Decimal(1)) for key in OUTCOME_KEYS},
        calibration_model_version="CALIBRATOR_V1",
        calibration_method="MULTINOMIAL_ISOTONIC_TEST",
        calibration_data_snapshot_id="calibration-data-v1",
        calibration_sample_count=300,
        calibration_visible_through=module.as_of,
    )

    assert snapshot.calibration_status is CalibrationStatus.CALIBRATED
    assert snapshot.probabilities == probabilities


def test_f26_probability_missing_key_bad_sum_and_version_mismatch_fail_closed() -> None:
    with pytest.raises(ValueError, match="exactly match"):
        validate_probability_simplex(
            {
                ProgressionOutcome.NEXT_PHASE_CONFIRMED.value: Decimal("0.5"),
                ProgressionOutcome.UNRESOLVED.value: Decimal("0.5"),
            }
        )
    with pytest.raises(ValueError, match="sum to one"):
        validate_probability_simplex(
            {
                ProgressionOutcome.NEXT_PHASE_CONFIRMED.value: Decimal("0.2"),
                ProgressionOutcome.SCENARIO_INVALIDATED.value: Decimal("0.2"),
                ProgressionOutcome.UNRESOLVED.value: Decimal("0.2"),
            }
        )
    scenario = make_scenario(
        make_pivots([100, 120, 110], first_type=PivotType.LOW),
        GrammarProfileKey.IMPULSE_STANDARD_V1,
    )
    module = build_module_snapshot(scenario)
    mismatch = build_probability_snapshot(
        module,
        calibration_status=CalibrationStatus.CALIBRATED,
        probabilities={
            ProgressionOutcome.NEXT_PHASE_CONFIRMED.value: Decimal("0.2"),
            ProgressionOutcome.SCENARIO_INVALIDATED.value: Decimal("0.3"),
            ProgressionOutcome.UNRESOLVED.value: Decimal("0.5"),
        },
        primary_outcome_key=ProgressionOutcome.UNRESOLVED.value,
        expected_outcome_space_version="SOME_NEW_OUTCOME_SPACE",
    )

    assert mismatch.calibration_status is CalibrationStatus.VERSION_MISMATCH
    assert mismatch.probabilities == {}


def test_f27_high_heuristic_without_calibrator_never_becomes_probability() -> None:
    scenario = replace(
        make_scenario(
            make_pivots([100, 120, 110], first_type=PivotType.LOW),
            GrammarProfileKey.IMPULSE_STANDARD_V1,
        ),
        heuristic_score=Decimal("0.82"),
    )
    module = build_module_snapshot(scenario)

    probability = build_probability_snapshot(
        module,
        calibration_status=CalibrationStatus.NOT_FITTED,
        status_reason="NO_ELIGIBLE_CALIBRATOR",
    )

    assert scenario.heuristic_score == Decimal("0.82")
    assert probability.probabilities == {}
    assert probability.primary_outcome_key is None
    assert probability.calibration_status is CalibrationStatus.NOT_FITTED


@pytest.mark.parametrize("forbidden_field", ["outcome_key", "outcome_at"])
def test_f28_online_feature_payload_rejects_future_outcome_fields(
    forbidden_field: str,
) -> None:
    scenario = make_scenario(
        make_pivots([100, 120, 110], first_type=PivotType.LOW),
        GrammarProfileKey.IMPULSE_STANDARD_V1,
    )
    with pytest.raises(ValueError, match="leaks outcome"):
        build_module_snapshot(scenario, feature_payload={forbidden_field: "future"})


@pytest.mark.parametrize("marker", ["MACD_7_52_7", "four_wave_P0_boundary"])
def test_f29_generic_profile_rejects_four_wave_special_markers(marker: str) -> None:
    with pytest.raises(ValueError, match="forbidden special marker"):
        validate_generic_profile_payload({"profile_key": marker})


@pytest.mark.parametrize("field", ["buy", "sell", "position", "trade_action"])
def test_f30_generic_output_schema_rejects_trading_instruction_fields(
    field: str,
) -> None:
    with pytest.raises(ValueError, match="trading fields"):
        assert_output_schema_is_research_only(["scenario_key", field])


def test_f31_unsupported_complex_grammar_is_not_forced_into_v1_profiles() -> None:
    pivots = make_pivots([100, 120, 105, 118], first_type=PivotType.LOW)
    profile, degree = fixed_profile_and_degree()

    result = generate_scenarios(
        pivots,
        degree=degree,
        detector=profile,
        as_of=pivots[-1].confirmed_at,
        bar_visible_through=pivots[-1].confirmed_at,
        grammar_profile_keys=("CONTRACTING_TRIANGLE_V1",),
    )

    assert result.generation_status is GenerationStatus.UNSUPPORTED
    assert result.snapshots == ()
    assert result.terminal_snapshots == ()


def test_f32_future_bars_cannot_change_t_snapshot_and_are_rejected_by_adapter() -> None:
    profile, degree = fixed_profile_and_degree()
    bars = detector_fixture_bars()
    generated_at = BASE_TIME + timedelta(days=100)
    prefix = bars[:3]

    prefix_result = replay_wave(
        prefix, detector=profile, degree=degree, created_at=generated_at
    ).final
    full_replay = replay_wave(
        bars, detector=profile, degree=degree, created_at=generated_at
    )

    assert full_replay.snapshots[2] == prefix_result
    with pytest.raises(InputContractError) as exc_info:
        detect_pivots(
            bars,
            profile=profile,
            degree=degree,
            as_of=prefix[-1].bar_end_at,
            created_at=generated_at,
        )
    assert exc_info.value.reason_code == "BAR_AFTER_AS_OF"


@pytest.mark.parametrize(
    ("ratio", "expected"),
    [
        (Decimal("0.618"), Decimal(1)),
        (Decimal("0.382"), Decimal("0.5")),
        (Decimal("0.332"), Decimal(0)),
        (Decimal("0.331"), Decimal(0)),
    ],
)
def test_f33_wave2_wave1_proximity_has_literal_boundary_values(
    ratio: Decimal, expected: Decimal
) -> None:
    assert proximity(ratio, "0.382", "0.618", "0.786", "0.05") == expected


@pytest.mark.parametrize(
    ("ratio", "expected"),
    [
        (Decimal("1.000"), Decimal(1)),
        (Decimal("1.618"), Decimal("0.5")),
        (Decimal("1.668"), Decimal(0)),
    ],
)
def test_f34_c_over_a_proximity_handles_ideal_equal_to_low(
    ratio: Decimal, expected: Decimal
) -> None:
    assert proximity(ratio, "1.000", "1.000", "1.618", "0.05") == expected


def test_f35_time_ratio_t3_is_six_over_eight() -> None:
    pivots = make_pivots([100, 120, 110, 150], first_type=PivotType.LOW)
    score = score_scenario(
        GrammarProfileKey.IMPULSE_STANDARD_V1,
        pivots,
        swings=make_swings(pivots, [8, 5, 6]),
    )
    time_feature = next(
        item for item in score.features if item.feature_key == "TIME_RATIO_FIT"
    )
    t3 = next(item for item in time_feature.components if item.component_key == "T3")

    assert t3.value == Decimal(6) / Decimal(8)
    assert t3.score == Decimal("0.75")


@pytest.mark.parametrize(
    ("ratio", "expected"),
    [
        (Decimal("0.5"), Decimal("0.5")),
        (Decimal("1.0"), Decimal(1)),
        (Decimal("2.0"), Decimal(0)),
    ],
)
def test_f36_t5_duration_proximity_has_literal_values(
    ratio: Decimal, expected: Decimal
) -> None:
    component = ratio_component(
        "T5",
        ratio,
        Decimal(1),
        RatioBand(Decimal("0.5"), Decimal("1"), Decimal("1.5"), Decimal("0.5")),
    )
    assert component.status is FeatureStatus.EVALUATED
    assert component.score == expected


def test_f37_wave2_wave4_alternation_combines_depth_and_time_differences() -> None:
    pivots = make_pivots([100, 200, 140, 240, 210], first_type=PivotType.LOW)
    score = score_scenario(
        GrammarProfileKey.IMPULSE_STANDARD_V1,
        pivots,
        swings=make_swings(pivots, [8, 5, 7, 10]),
    )
    feature = next(
        item for item in score.features if item.feature_key == "WAVE2_WAVE4_ALTERNATION"
    )
    depth = next(
        item for item in feature.components if item.component_key == "DEPTH_DIFFERENCE"
    )
    time = next(
        item for item in feature.components if item.component_key == "TIME_DIFFERENCE"
    )

    assert depth.value == Decimal("0.3")
    assert depth.score == Decimal("0.6")
    assert time.value == Decimal("0.5")
    assert time.score == Decimal("0.5")
    assert feature.feature_score == Decimal("0.55")


def test_f38_structure_completeness_uses_only_confirmed_legs() -> None:
    impulse = make_pivots([100, 120, 110, 150], first_type=PivotType.LOW)
    zigzag = make_pivots([160, 135, 150], first_type=PivotType.HIGH)

    impulse_score = score_scenario(GrammarProfileKey.IMPULSE_STANDARD_V1, impulse)
    zigzag_score = score_scenario(GrammarProfileKey.CORRECTIVE_ZIGZAG_V1, zigzag)
    impulse_feature = next(
        item
        for item in impulse_score.features
        if item.feature_key == "STRUCTURE_COMPLETENESS"
    )
    zigzag_feature = next(
        item
        for item in zigzag_score.features
        if item.feature_key == "STRUCTURE_COMPLETENESS"
    )

    assert impulse_feature.feature_score == Decimal("0.6")
    assert zigzag_feature.feature_score == Decimal(2) / Decimal(3)


def test_f39_evidence_weighted_score_matches_frozen_literal_formula() -> None:
    pivots = make_pivots([100, 200, Decimal("138.2"), 300], first_type=PivotType.LOW)
    score = score_scenario(
        GrammarProfileKey.IMPULSE_STANDARD_V1,
        pivots,
        swings=make_swings(pivots, [8, 5, 8]),
    )
    expected_ranking = Decimal("7.3") / Decimal(17)
    expected_coverage = Decimal("0.5")
    expected_heuristic = expected_ranking / expected_coverage

    assert score.ranking_score == expected_ranking
    assert score.score_coverage == expected_coverage
    assert score.heuristic_score == expected_heuristic
    assert score.ranking_score.quantize(Decimal("0.00000001")) == Decimal("0.42941176")
    assert score.heuristic_score.quantize(Decimal("0.00000001")) == Decimal(
        "0.85882353"
    )


def test_f40_channel_fit_is_never_filled_with_neutral_evidence_in_v1() -> None:
    pivots = make_pivots([100, 120, 110], first_type=PivotType.LOW)

    score = score_scenario(GrammarProfileKey.IMPULSE_STANDARD_V1, pivots)
    channel = next(item for item in score.features if item.feature_key == "CHANNEL_FIT")

    assert channel.feature_status is FeatureStatus.NOT_APPLICABLE
    assert channel.feature_score is None
    assert channel.feature_coverage == 0
    assert dict(IMPULSE_WEIGHTS_V1)["CHANNEL_FIT"] == 0
    assert channel.feature_reason == "CHANNEL_ALGORITHM_NOT_FROZEN_IN_SCORE_V1"


def test_f41_ranking_uses_evidence_mass_not_heuristic_alone() -> None:
    base = make_scenario(
        make_pivots([100, 120, 110], first_type=PivotType.LOW),
        GrammarProfileKey.IMPULSE_STANDARD_V1,
    )
    scenario_a = replace(
        base,
        scenario_key="scenario-a",
        heuristic_score=Decimal(1),
        score_coverage=Decimal("0.2"),
        ranking_score=Decimal("0.2"),
    )
    scenario_b = replace(
        base,
        scenario_key="scenario-b",
        heuristic_score=Decimal("0.8"),
        score_coverage=Decimal(1),
        ranking_score=Decimal("0.8"),
    )

    ranked, pruned = rank_scenarios((scenario_a, scenario_b), 5)

    assert pruned == 0
    assert [item.scenario_key for item in ranked] == ["scenario-b", "scenario-a"]
    assert [item.ranking_score for item in ranked] == [Decimal("0.8"), Decimal("0.2")]


@pytest.mark.parametrize(
    ("numerator", "denominator"),
    [
        (Decimal(1), Decimal(0)),
        (Decimal("NaN"), Decimal(1)),
        (Decimal(-1), Decimal(1)),
        (Decimal(1), Decimal(-1)),
    ],
)
def test_f42_invalid_ratio_is_not_yet_evaluable_not_zero_or_neutral(
    numerator: Decimal, denominator: Decimal
) -> None:
    band = dict(RATIO_BANDS_V1)["W2_W1"]

    component = ratio_component("W2_W1", numerator, denominator, band)

    assert component.status is FeatureStatus.NOT_YET_EVALUABLE
    assert component.value is None
    assert component.score is None


def test_f43_changing_v1_weight_without_new_version_is_rejected() -> None:
    original = dict(IMPULSE_WEIGHTS_V1)
    changed_weights = tuple(
        (
            key,
            original["TIME_RATIO_FIT"]
            if key == "FIBONACCI_RATIO_FIT"
            else original["FIBONACCI_RATIO_FIT"]
            if key == "TIME_RATIO_FIT"
            else value,
        )
        for key, value in IMPULSE_WEIGHTS_V1
    )

    with pytest.raises(ValueError, match="without a new version"):
        replace(SCORE_PROFILE_V1, impulse_weights=changed_weights)

    versioned = replace(
        SCORE_PROFILE_V1,
        score_profile_version="SCORE_PROFILE_V2_TEST",
        impulse_weights=changed_weights,
    )
    assert versioned.score_profile_version == "SCORE_PROFILE_V2_TEST"


def test_generic_row_adapter_preserves_order_and_rejects_unknown_continuity() -> None:
    first = make_bar(0, high=105, low=100, close=103)
    second = make_bar(1, high=106, low=101, close=104)
    rows = tuple(
        {
            "trade_date": bar.trade_date,
            "bar_end_at": bar.bar_end_at,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "vol": bar.vol,
            "amount": bar.amount,
            "source_partition": bar.source_partition,
        }
        for bar in (first, second)
    )

    adapted = adapt_canonical_rows(
        rows,
        ts_code="000001.SH",
        freq="1d",
        source_asset_key="fixture",
        source_contract_version="adapter-v1",
        data_snapshot_id="adapter-snapshot-v1",
        as_of=second.bar_end_at,
        continuity_status=ContinuityStatus.COMPLETE,
    )

    assert [bar.bar_end_at for bar in adapted] == [first.bar_end_at, second.bar_end_at]
    with pytest.raises(InputContractError, match="BAR_CONTINUITY_NOT_READY"):
        adapt_canonical_rows(
            rows,
            ts_code="000001.SH",
            freq="1d",
            source_asset_key="fixture",
            source_contract_version="adapter-v1",
            data_snapshot_id="adapter-snapshot-v1",
            as_of=second.bar_end_at,
            continuity_status=ContinuityStatus.UNKNOWN,
        )


def test_f44_same_prices_have_same_structure_semantics_in_all_four_frequencies() -> (
    None
):
    profile, degree = fixed_profile_and_degree()
    frequencies = ("1d", "120min", "60min", "30min")
    generated_at = BASE_TIME + timedelta(days=100)
    relative_pivots_by_freq: dict[str, tuple[tuple[object, ...], ...]] = {}
    semantics_by_freq: dict[str, set[tuple[object, ...]]] = {}
    keys_by_freq: dict[str, tuple[str, ...]] = {}

    for freq in frequencies:
        bars = detector_fixture_bars(freq=freq)
        full = replay_wave(
            bars,
            detector=profile,
            degree=degree,
            created_at=generated_at,
        )
        incremental = IncrementalWaveReplay(
            detector=profile, degree=degree, created_at=generated_at
        )
        incremental_final = None
        for bar in bars:
            incremental_final = incremental.append(bar)
        assert incremental_final == full.final
        index_by_bar_key = {bar.bar_key: index for index, bar in enumerate(bars)}
        relative_pivots_by_freq[freq] = tuple(
            (
                pivot.pivot_type,
                index_by_bar_key[pivot.extreme_bar_key],
                index_by_bar_key[pivot.confirmation_bar_key],
                pivot.extreme_price,
            )
            for pivot in full.final.detection.confirmations
        )
        all_scenarios = (
            full.final.confirmed_scenarios.snapshots
            + full.final.confirmed_scenarios.terminal_snapshots
        )
        semantics_by_freq[freq] = {
            (
                item.grammar_profile_key,
                item.scenario_type,
                item.direction,
                item.current_phase,
                item.confirmed_wave_count,
                item.scenario_status,
            )
            for item in all_scenarios
        }
        keys_by_freq[freq] = tuple(
            pivot.pivot_key for pivot in full.final.detection.confirmations
        )

    assert len(set(relative_pivots_by_freq.values())) == 1
    assert all(
        semantics == semantics_by_freq["1d"] for semantics in semantics_by_freq.values()
    )
    assert len(set(keys_by_freq.values())) == 4


def test_calibration_gate_accepts_only_out_of_sample_metrics_better_than_baseline() -> (
    None
):
    outcomes = (
        [ProgressionOutcome.NEXT_PHASE_CONFIRMED.value] * 40
        + [ProgressionOutcome.SCENARIO_INVALIDATED.value] * 40
        + [ProgressionOutcome.UNRESOLVED.value] * 20
    )
    records = tuple(
        CalibrationRecord(
            event_key=f"event-{index}",
            scenario_lineage_key=f"lineage-{index}",
            freq="1d",
            decision_as_of=BASE_TIME + timedelta(days=index),
            label_matured_at=BASE_TIME + timedelta(days=index + 20),
            actual_outcome=outcome,
            probabilities=tuple(
                sorted(
                    (
                        key,
                        Decimal("0.90") if key == outcome else Decimal("0.05"),
                    )
                    for key in OUTCOME_KEYS
                )
            ),
        )
        for index, outcome in enumerate(outcomes)
    )

    evaluation = evaluate_calibration_gate(
        calibration_sample_count=200,
        out_of_sample_records=records,
        baseline_probabilities={
            ProgressionOutcome.NEXT_PHASE_CONFIRMED.value: Decimal("0.4"),
            ProgressionOutcome.SCENARIO_INVALIDATED.value: Decimal("0.4"),
            ProgressionOutcome.UNRESOLVED.value: Decimal("0.2"),
        },
    )

    assert evaluation.calibration_status is CalibrationStatus.CALIBRATED
    assert evaluation.gate_failures == ()
    assert evaluation.multiclass_brier_score < evaluation.baseline_brier_score
    assert evaluation.log_loss < evaluation.baseline_log_loss
    assert evaluation.expected_calibration_error <= Decimal("0.10")


def test_temporal_split_rejects_lineage_leakage_and_unmatured_calibration_labels() -> (
    None
):
    probabilities = tuple(
        sorted(
            {
                ProgressionOutcome.NEXT_PHASE_CONFIRMED.value: Decimal("0.4"),
                ProgressionOutcome.SCENARIO_INVALIDATED.value: Decimal("0.4"),
                ProgressionOutcome.UNRESOLVED.value: Decimal("0.2"),
            }.items()
        )
    )
    train = CalibrationRecord(
        "event-train",
        "shared-lineage",
        "1d",
        BASE_TIME,
        BASE_TIME + timedelta(days=20),
        ProgressionOutcome.UNRESOLVED.value,
        probabilities,
    )
    calibration = CalibrationRecord(
        "event-calibration",
        "shared-lineage",
        "1d",
        BASE_TIME + timedelta(days=30),
        BASE_TIME + timedelta(days=60),
        ProgressionOutcome.UNRESOLVED.value,
        probabilities,
    )

    with pytest.raises(ValueError, match="lineage"):
        validate_temporal_split(
            {"train": (train,), "calibration": (calibration,)},
            calibration_visible_through=BASE_TIME + timedelta(days=100),
        )

    calibration_without_lineage_overlap = replace(
        calibration, scenario_lineage_key="calibration-lineage"
    )
    with pytest.raises(ValueError, match="visibility cutoff"):
        validate_temporal_split(
            {
                "train": (train,),
                "calibration": (calibration_without_lineage_overlap,),
            },
            calibration_visible_through=BASE_TIME + timedelta(days=50),
        )


def test_g1_static_boundary_has_no_dagster_dependency_or_period_specific_branch() -> (
    None
):
    package_root = (
        Path(__file__).parents[1] / "src" / "orchestrator" / "analysis" / "index_wave"
    )
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(package_root.glob("*.py"))
    )

    assert "import dagster" not in source.lower()
    assert "from dagster" not in source.lower()
    for period_literal in ('"1d"', '"120min"', '"60min"', '"30min"'):
        assert period_literal not in source
    assert {"buy", "sell", "position", "trade_action"}.isdisjoint(
        ScenarioSnapshot.__dataclass_fields__
    )
    assert {"outcome_key", "outcome_at"}.isdisjoint(
        AnalysisModuleSnapshot.__dataclass_fields__
    )


def test_causal_atr_detector_uses_mature_extreme_bar_threshold() -> None:
    bars = tuple(
        make_bar(index, high=101, low=99, close=100) for index in range(15)
    ) + (make_bar(15, high=102, low=99, close=102),)

    result = detect_pivots(
        bars,
        profile=CAUSAL_ATR_PROFILE,
        degree=BASE_DEGREE_PROFILE,
    )

    assert result.atr_values == wilder_atr(bars, 14)
    assert len(result.confirmations) == 1
    pivot = result.confirmations[0]
    assert pivot.pivot_type is PivotType.LOW
    assert pivot.extreme_at == bars[13].bar_end_at
    assert pivot.confirmed_at == bars[15].bar_end_at
    assert pivot.threshold_at_extreme == Decimal(3)


def test_equivalent_absolute_thresholds_share_one_profile_identity() -> None:
    assert (
        DetectorProfile.absolute_test(Decimal("5.0")).detector_profile_key
        == DetectorProfile.absolute_test(Decimal("5.00")).detector_profile_key
        == "ABSOLUTE_REVERSAL_TEST_5_V1"
    )


def test_historical_shanghai_daylight_saving_offset_is_not_hardcoded_to_utc8() -> None:
    historical_end = datetime(1990, 6, 1, 15, 0, tzinfo=SHANGHAI)
    bar = CanonicalBar(
        ts_code="000001.SH",
        freq="1d",
        trade_date=historical_end.date(),
        bar_end_at=historical_end,
        open=100,
        high=101,
        low=99,
        close=100,
        source_asset_key="fixture",
        source_partition="1990-06-01",
        source_contract_version="historical-timezone-v1",
        data_snapshot_id="historical-timezone-snapshot-v1",
    )

    assert validate_canonical_bars((bar,)) == (bar,)
    wrong_fixed_offset = replace(
        bar,
        bar_end_at=datetime(1990, 6, 1, 15, 0, tzinfo=timezone(timedelta(hours=8))),
    )
    with pytest.raises(InputContractError, match="BAR_TIMEZONE_INVALID"):
        validate_canonical_bars((wrong_fixed_offset,))
