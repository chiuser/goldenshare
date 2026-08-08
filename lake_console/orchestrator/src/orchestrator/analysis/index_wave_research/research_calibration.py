"""Temporal outcome calibration for the read-only index-wave research harness."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Final

from ..index_wave.calibration import (
    OUTCOME_KEYS,
    CalibrationEvaluation,
    CalibrationRecord,
    CalibrationStatus,
    evaluate_calibration_gate,
    validate_probability_simplex,
    validate_temporal_split,
)


CALIBRATION_MODEL_VERSION: Final = "HEURISTIC_BINNED_DIRICHLET_V1"
CALIBRATION_METHOD: Final = "FIXED_HEURISTIC_BINS_DIRICHLET_SHRINKAGE"
BIN_EDGES: Final = tuple(Decimal(item) for item in ("0", ".2", ".4", ".6", ".8", "1"))
DIRICHLET_PRIOR_STRENGTH: Final = Decimal(3)


@dataclass(frozen=True, slots=True)
class ResearchOutcomeRecord:
    event_key: str
    scenario_lineage_key: str
    freq: str
    decision_as_of: datetime
    label_matured_at: datetime
    actual_outcome: str
    heuristic_score: Decimal | None


@dataclass(frozen=True, slots=True)
class TemporalOutcomeSplit:
    train: tuple[ResearchOutcomeRecord, ...]
    calibration: tuple[ResearchOutcomeRecord, ...]
    test: tuple[ResearchOutcomeRecord, ...]
    train_embargoed: int
    calibration_embargoed: int
    calibration_start: datetime | None
    test_start: datetime | None


@dataclass(frozen=True, slots=True)
class BinnedDirichletModel:
    model_version: str
    baseline_probabilities: tuple[tuple[str, Decimal], ...]
    bin_probabilities: tuple[tuple[str, tuple[tuple[str, Decimal], ...]], ...]
    train_sample_count: int
    calibration_sample_count: int

    def predict(self, heuristic_score: Decimal | None) -> dict[str, Decimal]:
        probabilities = dict(
            dict(self.bin_probabilities)[heuristic_bin(heuristic_score)]
        )
        validate_probability_simplex(probabilities)
        return probabilities


@dataclass(frozen=True, slots=True)
class CalibrationAudit:
    model_version: str
    calibration_method: str
    train_sample_count: int
    calibration_sample_count: int
    out_of_sample_count: int
    train_embargoed: int
    calibration_embargoed: int
    calibration_status: CalibrationStatus
    gate_failures: tuple[str, ...]
    multiclass_brier_score: Decimal | None
    baseline_brier_score: Decimal | None
    log_loss: Decimal | None
    baseline_log_loss: Decimal | None
    expected_calibration_error: Decimal | None
    non_unresolved_counts: tuple[tuple[str, int], ...]
    probability_publication_allowed: bool


def heuristic_bin(score: Decimal | None) -> str:
    if score is None:
        return "MISSING"
    if not score.is_finite() or not Decimal(0) <= score <= Decimal(1):
        raise ValueError("heuristic score must be finite and in [0,1]")
    for lower, upper in zip(BIN_EDGES, BIN_EDGES[1:]):
        if lower <= score < upper or (upper == Decimal(1) and score == upper):
            return f"{lower}-{upper}"
    raise AssertionError("fixed bin edges do not cover the heuristic score")


def temporal_outcome_split(
    records: tuple[ResearchOutcomeRecord, ...] | list[ResearchOutcomeRecord],
) -> TemporalOutcomeSplit:
    """Apply chronological 60/20/20 cuts and embargo cross-boundary labels."""

    ordered = tuple(
        sorted(records, key=lambda item: (item.decision_as_of, item.event_key))
    )
    decision_times = tuple(sorted({item.decision_as_of for item in ordered}))
    if len(decision_times) < 3:
        return TemporalOutcomeSplit(ordered, (), (), 0, 0, None, None)
    calibration_index = min(
        len(decision_times) - 2, max(1, int(len(decision_times) * 0.6))
    )
    test_index = min(
        len(decision_times) - 1,
        max(calibration_index + 1, int(len(decision_times) * 0.8)),
    )
    calibration_start = decision_times[calibration_index]
    test_start = decision_times[test_index]
    raw_train = tuple(
        item for item in ordered if item.decision_as_of < calibration_start
    )
    raw_calibration = tuple(
        item
        for item in ordered
        if calibration_start <= item.decision_as_of < test_start
    )
    test = tuple(item for item in ordered if item.decision_as_of >= test_start)
    train = tuple(
        item for item in raw_train if item.label_matured_at < calibration_start
    )
    calibration = tuple(
        item for item in raw_calibration if item.label_matured_at < test_start
    )
    return TemporalOutcomeSplit(
        train=train,
        calibration=calibration,
        test=test,
        train_embargoed=len(raw_train) - len(train),
        calibration_embargoed=len(raw_calibration) - len(calibration),
        calibration_start=calibration_start,
        test_start=test_start,
    )


def fit_binned_dirichlet(
    split: TemporalOutcomeSplit,
) -> BinnedDirichletModel:
    if not split.train:
        raise ValueError("at least one training record is required")
    train_counts = Counter(item.actual_outcome for item in split.train)
    unknown = set(train_counts).difference(OUTCOME_KEYS)
    if unknown:
        raise ValueError(
            f"training records contain unknown outcomes: {sorted(unknown)}"
        )
    denominator = Decimal(len(split.train) + len(OUTCOME_KEYS))
    baseline = {
        key: Decimal(train_counts[key] + 1) / denominator for key in OUTCOME_KEYS
    }
    by_bin: dict[str, Counter[str]] = defaultdict(Counter)
    for record in split.calibration:
        if record.actual_outcome not in OUTCOME_KEYS:
            raise ValueError("calibration record contains an unknown outcome")
        by_bin[heuristic_bin(record.heuristic_score)][record.actual_outcome] += 1
    all_bins = ("MISSING",) + tuple(
        f"{lower}-{upper}" for lower, upper in zip(BIN_EDGES, BIN_EDGES[1:])
    )
    bin_probabilities: list[tuple[str, tuple[tuple[str, Decimal], ...]]] = []
    for bin_key in all_bins:
        counts = by_bin[bin_key]
        bin_denominator = Decimal(sum(counts.values())) + DIRICHLET_PRIOR_STRENGTH
        probabilities = {
            key: (Decimal(counts[key]) + DIRICHLET_PRIOR_STRENGTH * baseline[key])
            / bin_denominator
            for key in OUTCOME_KEYS
        }
        validate_probability_simplex(probabilities)
        bin_probabilities.append((bin_key, tuple(sorted(probabilities.items()))))
    return BinnedDirichletModel(
        model_version=CALIBRATION_MODEL_VERSION,
        baseline_probabilities=tuple(sorted(baseline.items())),
        bin_probabilities=tuple(bin_probabilities),
        train_sample_count=len(split.train),
        calibration_sample_count=len(split.calibration),
    )


def _calibration_record(
    record: ResearchOutcomeRecord, probabilities: dict[str, Decimal]
) -> CalibrationRecord:
    return CalibrationRecord(
        event_key=record.event_key,
        scenario_lineage_key=record.scenario_lineage_key,
        freq=record.freq,
        decision_as_of=record.decision_as_of,
        label_matured_at=record.label_matured_at,
        actual_outcome=record.actual_outcome,
        probabilities=tuple(sorted(probabilities.items())),
    )


def _empty_audit(split: TemporalOutcomeSplit, *failures: str) -> CalibrationAudit:
    return CalibrationAudit(
        model_version=CALIBRATION_MODEL_VERSION,
        calibration_method=CALIBRATION_METHOD,
        train_sample_count=len(split.train),
        calibration_sample_count=len(split.calibration),
        out_of_sample_count=len(split.test),
        train_embargoed=split.train_embargoed,
        calibration_embargoed=split.calibration_embargoed,
        calibration_status=CalibrationStatus.INSUFFICIENT_SAMPLE,
        gate_failures=failures,
        multiclass_brier_score=None,
        baseline_brier_score=None,
        log_loss=None,
        baseline_log_loss=None,
        expected_calibration_error=None,
        non_unresolved_counts=(),
        probability_publication_allowed=False,
    )


def run_calibration_audit(
    records: tuple[ResearchOutcomeRecord, ...] | list[ResearchOutcomeRecord],
) -> CalibrationAudit:
    split = temporal_outcome_split(records)
    if not split.train:
        return _empty_audit(split, "TRAIN_SAMPLE_EMPTY")
    model = fit_binned_dirichlet(split)
    if not split.test:
        return _empty_audit(split, "OUT_OF_SAMPLE_LT_100")
    uniform = {key: Decimal(1) / Decimal(len(OUTCOME_KEYS)) for key in OUTCOME_KEYS}
    train_records = tuple(_calibration_record(item, uniform) for item in split.train)
    calibration_records = tuple(
        _calibration_record(item, uniform) for item in split.calibration
    )
    test_records = tuple(
        _calibration_record(item, model.predict(item.heuristic_score))
        for item in split.test
    )
    validate_temporal_split(
        {
            "train": train_records,
            "calibration": calibration_records,
            "test": test_records,
        },
        calibration_visible_through=split.test_start or split.test[-1].decision_as_of,
    )
    evaluation: CalibrationEvaluation = evaluate_calibration_gate(
        calibration_sample_count=len(split.calibration),
        out_of_sample_records=test_records,
        baseline_probabilities=dict(model.baseline_probabilities),
    )
    return CalibrationAudit(
        model_version=CALIBRATION_MODEL_VERSION,
        calibration_method=CALIBRATION_METHOD,
        train_sample_count=len(split.train),
        calibration_sample_count=evaluation.calibration_sample_count,
        out_of_sample_count=evaluation.out_of_sample_count,
        train_embargoed=split.train_embargoed,
        calibration_embargoed=split.calibration_embargoed,
        calibration_status=evaluation.calibration_status,
        gate_failures=evaluation.gate_failures,
        multiclass_brier_score=evaluation.multiclass_brier_score,
        baseline_brier_score=evaluation.baseline_brier_score,
        log_loss=evaluation.log_loss,
        baseline_log_loss=evaluation.baseline_log_loss,
        expected_calibration_error=evaluation.expected_calibration_error,
        non_unresolved_counts=evaluation.non_unresolved_counts,
        probability_publication_allowed=(
            evaluation.calibration_status is CalibrationStatus.CALIBRATED
        ),
    )
