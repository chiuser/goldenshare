"""Probability contract, leakage gates, and calibration evaluation harness."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from math import log
from typing import Mapping, Sequence

from .progression import (
    ANALYSIS_MODULE_KEY,
    OUTCOME_SPACE_VERSION,
    AnalysisModuleSnapshot,
    ProgressionOutcome,
)


OUTCOME_KEYS = tuple(item.value for item in ProgressionOutcome)


class CalibrationStatus(str, Enum):
    CALIBRATED = "CALIBRATED"
    NOT_FITTED = "NOT_FITTED"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    STALE = "STALE"
    VERSION_MISMATCH = "VERSION_MISMATCH"


@dataclass(frozen=True, slots=True)
class ProbabilitySnapshot:
    analysis_module_key: str
    module_snapshot_id: str
    scenario_key: str
    scenario_lineage_key: str
    ts_code: str
    freq: str
    as_of: datetime
    outcome_space_version: str
    horizon_value: int
    horizon_unit: str
    label_version: str
    scenario_model_version: str
    scenario_score_profile_version: str
    scenario_data_snapshot_id: str
    feature_contract_version: str
    calibration_model_version: str | None
    calibration_method: str | None
    calibration_data_snapshot_id: str | None
    outcome_probabilities: tuple[tuple[str, Decimal], ...]
    primary_outcome_key: str | None
    outcome_intervals: tuple[tuple[str, tuple[Decimal, Decimal]], ...]
    calibration_sample_count: int
    calibration_status: CalibrationStatus
    calibration_visible_through: datetime | None
    status_reason: str

    def __post_init__(self) -> None:
        probabilities = dict(self.outcome_probabilities)
        if self.calibration_status is CalibrationStatus.CALIBRATED:
            validate_probability_simplex(probabilities)
            intervals = dict(self.outcome_intervals)
            if set(intervals) != set(OUTCOME_KEYS):
                raise ValueError("calibrated intervals must match the outcome space")
            if any(
                lower < 0 or upper > 1 or lower > upper
                for lower, upper in intervals.values()
            ):
                raise ValueError(
                    "probability intervals must satisfy 0 <= lower <= upper <= 1"
                )
            if self.primary_outcome_key not in OUTCOME_KEYS:
                raise ValueError("primary outcome is outside the current outcome space")
            if not all(
                (
                    self.calibration_model_version,
                    self.calibration_method,
                    self.calibration_data_snapshot_id,
                    self.calibration_visible_through,
                )
            ):
                raise ValueError("calibrated probability requires complete lineage")
        elif (
            probabilities
            or self.outcome_intervals
            or self.primary_outcome_key is not None
        ):
            raise ValueError("non-calibrated status must return empty probabilities")

    @property
    def probabilities(self) -> dict[str, Decimal]:
        return dict(self.outcome_probabilities)


def validate_probability_simplex(
    probabilities: Mapping[str, Decimal | int | float | str],
    *,
    tolerance: Decimal = Decimal("0.00000001"),
) -> None:
    if set(probabilities) != set(OUTCOME_KEYS):
        raise ValueError("probability keys must exactly match the outcome space")
    converted = {key: Decimal(str(value)) for key, value in probabilities.items()}
    if any(
        not value.is_finite() or value < 0 or value > 1 for value in converted.values()
    ):
        raise ValueError("each probability must be finite and in [0,1]")
    if abs(sum(converted.values(), Decimal(0)) - Decimal(1)) > tolerance:
        raise ValueError("probabilities must sum to one")


def build_probability_snapshot(
    module_snapshot: AnalysisModuleSnapshot,
    *,
    calibration_status: CalibrationStatus,
    probabilities: Mapping[str, Decimal | int | float | str] | None = None,
    primary_outcome_key: str | None = None,
    outcome_intervals: Mapping[str, tuple[Decimal, Decimal]] | None = None,
    calibration_model_version: str | None = None,
    calibration_method: str | None = None,
    calibration_data_snapshot_id: str | None = None,
    calibration_sample_count: int = 0,
    calibration_visible_through: datetime | None = None,
    status_reason: str = "",
    expected_outcome_space_version: str = OUTCOME_SPACE_VERSION,
    expected_feature_contract_version: str | None = None,
) -> ProbabilitySnapshot:
    if module_snapshot.outcome_space_version != expected_outcome_space_version or (
        expected_feature_contract_version is not None
        and module_snapshot.feature_contract_version
        != expected_feature_contract_version
    ):
        calibration_status = CalibrationStatus.VERSION_MISMATCH
        probabilities = None
        primary_outcome_key = None
        outcome_intervals = None
        status_reason = "UPSTREAM_CONTRACT_VERSION_MISMATCH"
    probability_items = tuple(
        sorted(
            (key, Decimal(str(value))) for key, value in (probabilities or {}).items()
        )
    )
    interval_items = tuple(sorted((outcome_intervals or {}).items()))
    return ProbabilitySnapshot(
        analysis_module_key=ANALYSIS_MODULE_KEY,
        module_snapshot_id=module_snapshot.module_snapshot_id,
        scenario_key=module_snapshot.scenario_key,
        scenario_lineage_key=module_snapshot.scenario_lineage_key,
        ts_code=module_snapshot.ts_code,
        freq=module_snapshot.freq,
        as_of=module_snapshot.as_of,
        outcome_space_version=module_snapshot.outcome_space_version,
        horizon_value=module_snapshot.horizon_value,
        horizon_unit=module_snapshot.horizon_unit,
        label_version=module_snapshot.label_version,
        scenario_model_version=module_snapshot.scenario_model_version,
        scenario_score_profile_version=module_snapshot.scenario_score_profile_version,
        scenario_data_snapshot_id=module_snapshot.scenario_data_snapshot_id,
        feature_contract_version=module_snapshot.feature_contract_version,
        calibration_model_version=calibration_model_version,
        calibration_method=calibration_method,
        calibration_data_snapshot_id=calibration_data_snapshot_id,
        outcome_probabilities=probability_items,
        primary_outcome_key=primary_outcome_key,
        outcome_intervals=interval_items,
        calibration_sample_count=calibration_sample_count,
        calibration_status=calibration_status,
        calibration_visible_through=calibration_visible_through,
        status_reason=status_reason,
    )


@dataclass(frozen=True, slots=True)
class CalibrationRecord:
    event_key: str
    scenario_lineage_key: str
    freq: str
    decision_as_of: datetime
    label_matured_at: datetime
    actual_outcome: str
    probabilities: tuple[tuple[str, Decimal], ...]


@dataclass(frozen=True, slots=True)
class CalibrationEvaluation:
    calibration_sample_count: int
    out_of_sample_count: int
    non_unresolved_counts: tuple[tuple[str, int], ...]
    multiclass_brier_score: Decimal
    baseline_brier_score: Decimal
    log_loss: Decimal
    baseline_log_loss: Decimal
    expected_calibration_error: Decimal
    calibration_status: CalibrationStatus
    gate_failures: tuple[str, ...]


def _metrics(records: Sequence[CalibrationRecord]) -> tuple[Decimal, Decimal, Decimal]:
    if not records:
        raise ValueError("at least one record is required")
    brier_total = 0.0
    log_total = 0.0
    confidence_accuracy: list[tuple[float, float]] = []
    for record in records:
        probabilities = {key: float(value) for key, value in record.probabilities}
        validate_probability_simplex(probabilities)
        if record.actual_outcome not in OUTCOME_KEYS:
            raise ValueError("actual outcome is outside the current outcome space")
        brier_total += sum(
            (probabilities[key] - (1.0 if record.actual_outcome == key else 0.0)) ** 2
            for key in OUTCOME_KEYS
        )
        actual_probability = max(1e-15, probabilities[record.actual_outcome])
        log_total += -log(actual_probability)
        predicted = max(OUTCOME_KEYS, key=lambda key: probabilities[key])
        confidence_accuracy.append(
            (
                probabilities[predicted],
                1.0 if predicted == record.actual_outcome else 0.0,
            )
        )
    ece = 0.0
    bin_count = 10
    for bin_index in range(bin_count):
        lower = bin_index / bin_count
        upper = (bin_index + 1) / bin_count
        members = [
            item
            for item in confidence_accuracy
            if (
                lower <= item[0] <= upper
                if bin_index == bin_count - 1
                else lower <= item[0] < upper
            )
        ]
        if members:
            mean_confidence = sum(item[0] for item in members) / len(members)
            mean_accuracy = sum(item[1] for item in members) / len(members)
            ece += len(members) / len(records) * abs(mean_accuracy - mean_confidence)
    count = len(records)
    return (
        Decimal(str(brier_total / count)),
        Decimal(str(log_total / count)),
        Decimal(str(ece)),
    )


def evaluate_calibration_gate(
    *,
    calibration_sample_count: int,
    out_of_sample_records: Sequence[CalibrationRecord],
    baseline_probabilities: Mapping[str, Decimal | int | float | str],
) -> CalibrationEvaluation:
    validate_probability_simplex(baseline_probabilities)
    if len({record.freq for record in out_of_sample_records}) > 1:
        raise ValueError("one calibration evaluation cannot mix frequencies")
    brier, log_loss, ece = _metrics(out_of_sample_records)
    baseline_records = tuple(
        CalibrationRecord(
            event_key=record.event_key,
            scenario_lineage_key=record.scenario_lineage_key,
            freq=record.freq,
            decision_as_of=record.decision_as_of,
            label_matured_at=record.label_matured_at,
            actual_outcome=record.actual_outcome,
            probabilities=tuple(
                sorted(
                    (key, Decimal(str(value)))
                    for key, value in baseline_probabilities.items()
                )
            ),
        )
        for record in out_of_sample_records
    )
    baseline_brier, baseline_log, _ = _metrics(baseline_records)
    counts = {
        key: sum(record.actual_outcome == key for record in out_of_sample_records)
        for key in OUTCOME_KEYS
        if key != ProgressionOutcome.UNRESOLVED.value
    }
    failures: list[str] = []
    if calibration_sample_count < 200:
        failures.append("CALIBRATION_SAMPLE_LT_200")
    if len(out_of_sample_records) < 100:
        failures.append("OUT_OF_SAMPLE_LT_100")
    if any(count < 20 for count in counts.values()):
        failures.append("NON_UNRESOLVED_CLASS_LT_20")
    if brier > baseline_brier:
        failures.append("BRIER_WORSE_THAN_BASELINE")
    if log_loss > baseline_log:
        failures.append("LOG_LOSS_WORSE_THAN_BASELINE")
    if ece > Decimal("0.10"):
        failures.append("ECE_GT_0_10")
    status = (
        CalibrationStatus.CALIBRATED
        if not failures
        else CalibrationStatus.INSUFFICIENT_SAMPLE
        if any("SAMPLE" in item or "CLASS" in item for item in failures)
        else CalibrationStatus.NOT_FITTED
    )
    return CalibrationEvaluation(
        calibration_sample_count=calibration_sample_count,
        out_of_sample_count=len(out_of_sample_records),
        non_unresolved_counts=tuple(sorted(counts.items())),
        multiclass_brier_score=brier,
        baseline_brier_score=baseline_brier,
        log_loss=log_loss,
        baseline_log_loss=baseline_log,
        expected_calibration_error=ece,
        calibration_status=status,
        gate_failures=tuple(failures),
    )


def validate_temporal_split(
    splits: Mapping[str, Sequence[CalibrationRecord]],
    *,
    calibration_visible_through: datetime,
) -> None:
    seen_event: dict[str, str] = {}
    seen_lineage: dict[str, str] = {}
    for split_name, records in splits.items():
        for record in records:
            if (
                record.event_key in seen_event
                and seen_event[record.event_key] != split_name
            ):
                raise ValueError("event_key appears in multiple temporal splits")
            if (
                record.scenario_lineage_key in seen_lineage
                and seen_lineage[record.scenario_lineage_key] != split_name
            ):
                raise ValueError("scenario lineage appears in multiple temporal splits")
            seen_event[record.event_key] = split_name
            seen_lineage[record.scenario_lineage_key] = split_name
            if (
                split_name == "calibration"
                and record.label_matured_at > calibration_visible_through
            ):
                raise ValueError(
                    "calibration label matured after calibration visibility cutoff"
                )
    previous_max: datetime | None = None
    for split_name in ("train", "calibration", "test"):
        times = tuple(record.decision_as_of for record in splits.get(split_name, ()))
        if not times:
            continue
        if previous_max is not None and min(times) <= previous_max:
            raise ValueError("train/calibration/test splits are not chronological")
        previous_max = max(times)
