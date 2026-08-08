from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from orchestrator.analysis.index_wave import (
    BASE_DEGREE_PROFILE,
    CAUSAL_ATR_PROFILE,
    CanonicalBar,
    IncrementalWaveReplay,
    ScenarioStatus,
)
from orchestrator.analysis.index_wave.calibration import OUTCOME_KEYS
from orchestrator.analysis.index_wave_research.research_calibration import (
    ResearchOutcomeRecord,
    fit_binned_dirichlet,
    run_calibration_audit,
    temporal_outcome_split,
)
from orchestrator.analysis.index_wave_research.research_validation import (
    detect_causal_five_bar_fractals,
    progression_observation_for_lineage,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _bar(index: int, high: int, low: int) -> CanonicalBar:
    trade_date = date(2026, 1, index + 1)
    return CanonicalBar(
        ts_code="000001.SH",
        freq="1d",
        trade_date=trade_date,
        bar_end_at=datetime(2026, 1, index + 1, 15, 0, tzinfo=SHANGHAI),
        open=Decimal(low + 1),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(high - 1),
        source_asset_key="test",
        source_partition=trade_date.isoformat(),
        source_contract_version="TEST_V1",
        data_snapshot_id="snapshot",
    )


def _outcome_record(
    index: int,
    *,
    decision: datetime,
    matured: datetime,
    outcome: str = "unresolved",
) -> ResearchOutcomeRecord:
    return ResearchOutcomeRecord(
        event_key=f"event-{index}",
        scenario_lineage_key=f"lineage-{index}",
        freq="1d",
        decision_as_of=decision,
        label_matured_at=matured,
        actual_outcome=outcome,
        heuristic_score=Decimal(index % 10) / Decimal(10),
    )


def test_five_bar_fractal_is_confirmed_two_closed_bars_after_extreme() -> None:
    bars = tuple(
        _bar(index, high, low)
        for index, (high, low) in enumerate(((3, 2), (4, 2), (8, 3), (5, 2), (4, 2)))
    )

    pivots = detect_causal_five_bar_fractals(bars)

    assert len(pivots) == 1
    assert pivots[0].pivot_type == "HIGH"
    assert pivots[0].extreme_at == bars[2].bar_end_at
    assert pivots[0].confirmed_at == bars[4].bar_end_at
    assert pivots[0].confirmation_delay_bars == 2


def test_streaming_replay_can_avoid_retaining_duplicate_snapshot_history() -> None:
    replay = IncrementalWaveReplay(
        detector=CAUSAL_ATR_PROFILE,
        degree=BASE_DEGREE_PROFILE,
        retain_snapshots=False,
    )

    snapshot = replay.append(_bar(0, 3, 1))

    assert snapshot.as_of == datetime(2026, 1, 1, 15, 0, tzinfo=SHANGHAI)
    assert replay.snapshots == ()


def test_progression_observation_retains_same_bar_phase_and_invalidation() -> None:
    scenarios = (
        SimpleNamespace(
            scenario_lineage_key="lineage-1",
            confirmed_wave_count=3,
            scenario_status=ScenarioStatus.INVALIDATED,
            invalidation_rule_key="RULE_1",
        ),
    )

    observation = progression_observation_for_lineage(
        scenario_lineage_key="lineage-1",
        decision_wave_count=2,
        bar_end_at=datetime(2026, 1, 8, 15, 0, tzinfo=SHANGHAI),
        current_scenarios=scenarios,  # type: ignore[arg-type]
    )

    assert observation.next_phase_confirmed is True
    assert observation.scenario_invalidated is True
    assert observation.trigger_rule_key == "RULE_1"


def test_temporal_split_embargoes_labels_visible_after_next_split() -> None:
    start = datetime(2026, 1, 1, 15, 0, tzinfo=SHANGHAI)
    decisions = tuple(start + timedelta(days=index) for index in range(5))
    records = [
        _outcome_record(
            index,
            decision=decision,
            matured=(decisions[3] if index == 0 else decision + timedelta(hours=1)),
        )
        for index, decision in enumerate(decisions)
    ]

    split = temporal_outcome_split(records)

    assert split.calibration_start == decisions[3]
    assert split.test_start == decisions[4]
    assert split.train_embargoed == 1
    assert all(item.label_matured_at < split.calibration_start for item in split.train)
    assert all(item.label_matured_at < split.test_start for item in split.calibration)


def test_binned_dirichlet_predictions_form_a_probability_simplex() -> None:
    start = datetime(2020, 1, 1, 15, 0, tzinfo=SHANGHAI)
    records = [
        _outcome_record(
            index,
            decision=start + timedelta(days=index),
            matured=start + timedelta(days=index, hours=1),
            outcome=OUTCOME_KEYS[index % len(OUTCOME_KEYS)],
        )
        for index in range(30)
    ]
    model = fit_binned_dirichlet(temporal_outcome_split(records))

    probabilities = model.predict(Decimal("0.72"))

    assert set(probabilities) == set(OUTCOME_KEYS)
    assert abs(sum(probabilities.values(), Decimal(0)) - Decimal(1)) < Decimal("1e-20")
    assert all(Decimal(0) <= value <= Decimal(1) for value in probabilities.values())


def test_probability_gate_fails_closed_when_samples_are_insufficient() -> None:
    start = datetime(2020, 1, 1, 15, 0, tzinfo=SHANGHAI)
    records = [
        _outcome_record(
            index,
            decision=start + timedelta(days=index),
            matured=start + timedelta(days=index, hours=1),
            outcome=OUTCOME_KEYS[index % len(OUTCOME_KEYS)],
        )
        for index in range(120)
    ]

    audit = run_calibration_audit(records)

    assert audit.probability_publication_allowed is False
    assert "CALIBRATION_SAMPLE_LT_200" in audit.gate_failures
    assert "OUT_OF_SAMPLE_LT_100" in audit.gate_failures
