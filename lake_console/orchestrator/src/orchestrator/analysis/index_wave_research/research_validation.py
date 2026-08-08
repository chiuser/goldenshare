"""Causal, read-only real-data validation runner for the index-wave engine."""

from __future__ import annotations

import argparse
import gc
import json
import resource
import statistics
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Final
from zoneinfo import ZoneInfo

from ..index_wave.bars import CanonicalBar
from ..index_wave.grammar import ScenarioStatus
from ..index_wave.profiles import BASE_DEGREE_PROFILE, CAUSAL_ATR_PROFILE
from ..index_wave.progression import (
    LabelingStatus,
    ProgressionObservation,
    build_module_snapshot,
    label_progression,
)
from ..index_wave.replay import ReplaySnapshot, iter_wave_replay
from .research_calibration import (
    CalibrationAudit,
    ResearchOutcomeRecord,
    run_calibration_audit,
)
from .research_sources import (
    DEFAULT_LAKE_ROOT,
    MAJOR_INDEX_RESEARCH_CODES,
    SUPPORTED_RESEARCH_FREQUENCIES,
    IndexWaveLakeReader,
    LoadedSeries,
    SourceManifest,
    build_source_manifest,
)
from ..index_wave.scenarios import ScenarioSnapshot


RESEARCH_RUNNER_VERSION: Final = "INDEX_WAVE_READONLY_VALIDATION_V1"
COMPARISON_DETECTOR_VERSION: Final = "CAUSAL_FIVE_BAR_FRACTAL_V1"
RESEARCH_HORIZONS: Final = (10, 20, 40)


@dataclass(frozen=True, slots=True)
class FractalPivot:
    pivot_type: str
    extreme_at: datetime
    confirmed_at: datetime
    confirmation_delay_bars: int


@dataclass(slots=True)
class _ProgressionEventBuilder:
    scenario: ScenarioSnapshot
    observations: list[ProgressionObservation]


@dataclass(frozen=True, slots=True)
class SeriesResearchResult:
    ts_code: str
    freq: str
    bar_count: int
    trade_date_count: int
    first_bar_at: datetime
    last_bar_at: datetime
    source_exclusion_count: int
    source_exclusion_reasons: tuple[tuple[str, int], ...]
    confirmed_pivot_count: int
    pivot_density_per_100_bars: float
    pivot_confirmation_delay_mean_bars: float | None
    pivot_confirmation_delay_median_bars: float | None
    fractal_pivot_count: int
    fractal_density_per_100_bars: float
    fractal_confirmation_delay_bars: int
    scenario_snapshot_count: int
    unique_scenario_count: int
    unique_lineage_count: int
    active_event_count: int
    empty_scenario_bar_count: int
    top_lineage_stability_rate: float | None
    top_lineage_change_count: int
    matured_label_counts: tuple[tuple[int, int], ...]
    outcome_counts_20_bar: tuple[tuple[str, int], ...]
    source_load_seconds: float
    analysis_seconds: float
    peak_memory_bytes: int
    anomalies: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SeriesAnalysis:
    result: SeriesResearchResult
    primary_records: tuple[ResearchOutcomeRecord, ...]


@dataclass(frozen=True, slots=True)
class SeriesFailure:
    ts_code: str
    freq: str
    bar_count: int
    first_bar_at: datetime
    last_bar_at: datetime
    reason_code: str
    detail: str


class WaveReplayFailure(RuntimeError):
    """A contextualized per-series research failure, not a process failure."""


def detect_causal_five_bar_fractals(
    bars: tuple[CanonicalBar, ...] | list[CanonicalBar],
) -> tuple[FractalPivot, ...]:
    """Confirm a strict five-bar fractal only after both right bars are closed."""

    materialized = tuple(bars)
    pivots: list[FractalPivot] = []
    for center_index in range(2, len(materialized) - 2):
        center = materialized[center_index]
        neighbours = (
            materialized[center_index - 2 : center_index]
            + materialized[center_index + 1 : center_index + 3]
        )
        high = all(center.high > item.high for item in neighbours)
        low = all(center.low < item.low for item in neighbours)
        if high == low:
            continue
        pivots.append(
            FractalPivot(
                pivot_type="HIGH" if high else "LOW",
                extreme_at=center.bar_end_at,
                confirmed_at=materialized[center_index + 2].bar_end_at,
                confirmation_delay_bars=2,
            )
        )
    return tuple(pivots)


def progression_observation_for_lineage(
    *,
    scenario_lineage_key: str,
    decision_wave_count: int,
    bar_end_at: datetime,
    current_scenarios: tuple[ScenarioSnapshot, ...],
) -> ProgressionObservation:
    matching = tuple(
        item
        for item in current_scenarios
        if item.scenario_lineage_key == scenario_lineage_key
    )
    invalidated = next(
        (
            item
            for item in matching
            if item.scenario_status is ScenarioStatus.INVALIDATED
        ),
        None,
    )
    return ProgressionObservation(
        bar_end_at=bar_end_at,
        next_phase_confirmed=any(
            item.confirmed_wave_count > decision_wave_count for item in matching
        ),
        scenario_invalidated=invalidated is not None,
        trigger_rule_key=(
            invalidated.invalidation_rule_key if invalidated is not None else None
        ),
    )


def _series_replay(loaded: LoadedSeries):
    try:
        yield from iter_wave_replay(
            loaded.bars,
            detector=CAUSAL_ATR_PROFILE,
            degree=BASE_DEGREE_PROFILE,
        )
    except (AssertionError, ValueError) as exc:
        raise WaveReplayFailure(
            f"WAVE_REPLAY_FAILED: {loaded.ts_code}/{loaded.freq}: {exc}"
        ) from exc


def _pivot_delays(
    bars: tuple[CanonicalBar, ...], final_snapshot: ReplaySnapshot
) -> tuple[int, ...]:
    index_by_time = {bar.bar_end_at: index for index, bar in enumerate(bars)}
    return tuple(
        index_by_time[pivot.confirmed_at] - index_by_time[pivot.extreme_at]
        for pivot in final_snapshot.detection.confirmations
    )


def _label_events(
    builders: tuple[_ProgressionEventBuilder, ...],
) -> tuple[
    tuple[tuple[int, int], ...],
    tuple[tuple[str, int], ...],
    tuple[ResearchOutcomeRecord, ...],
]:
    matured_counts: Counter[int] = Counter()
    primary_outcomes: Counter[str] = Counter()
    primary_records: list[ResearchOutcomeRecord] = []
    for builder in builders:
        for horizon in RESEARCH_HORIZONS:
            module = build_module_snapshot(
                builder.scenario,
                feature_payload={
                    "heuristic_score": (
                        str(builder.scenario.heuristic_score)
                        if builder.scenario.heuristic_score is not None
                        else None
                    ),
                    "score_coverage": str(builder.scenario.score_coverage),
                    "confirmed_wave_count": builder.scenario.confirmed_wave_count,
                },
                horizon_bars=horizon,
            )
            labeling = label_progression(module, builder.observations)
            if labeling.status is not LabelingStatus.MATURED:
                continue
            assert labeling.label is not None
            matured_counts[horizon] += 1
            if horizon != 20:
                continue
            label = labeling.label
            primary_outcomes[label.outcome_key.value] += 1
            primary_records.append(
                ResearchOutcomeRecord(
                    event_key=label.event_key,
                    scenario_lineage_key=label.scenario_lineage_key,
                    freq=label.freq,
                    decision_as_of=label.decision_as_of,
                    label_matured_at=label.label_matured_at,
                    actual_outcome=label.outcome_key.value,
                    heuristic_score=builder.scenario.heuristic_score,
                )
            )
    return (
        tuple((horizon, matured_counts[horizon]) for horizon in RESEARCH_HORIZONS),
        tuple(sorted(primary_outcomes.items())),
        tuple(primary_records),
    )


def analyze_loaded_series(loaded: LoadedSeries) -> SeriesAnalysis:
    bars = loaded.bars
    started = time.perf_counter()
    builders: list[_ProgressionEventBuilder] = []
    open_builders: list[_ProgressionEventBuilder] = []
    seen_active_lineages: set[str] = set()
    scenario_keys: set[str] = set()
    lineage_keys: set[str] = set()
    scenario_snapshot_count = 0
    empty_scenario_bars = 0
    previous_top: str | None = None
    stability_comparisons = 0
    stable_top_count = 0
    top_lineage_changes = 0
    final_snapshot: ReplaySnapshot | None = None

    for replay_snapshot in _series_replay(loaded):
        final_snapshot = replay_snapshot
        current = (
            replay_snapshot.confirmed_scenarios.snapshots
            + replay_snapshot.confirmed_scenarios.terminal_snapshots
        )
        for builder in open_builders:
            builder.observations.append(
                progression_observation_for_lineage(
                    scenario_lineage_key=builder.scenario.scenario_lineage_key,
                    decision_wave_count=builder.scenario.confirmed_wave_count,
                    bar_end_at=replay_snapshot.as_of,
                    current_scenarios=current,
                )
            )
        open_builders = [
            builder
            for builder in open_builders
            if len(builder.observations) < max(RESEARCH_HORIZONS)
        ]

        ranked = replay_snapshot.confirmed_scenarios.snapshots
        scenario_snapshot_count += len(current)
        scenario_keys.update(item.scenario_key for item in current)
        lineage_keys.update(item.scenario_lineage_key for item in current)
        if not current:
            empty_scenario_bars += 1
        current_top = ranked[0].scenario_lineage_key if ranked else None
        if previous_top is not None and current_top is not None:
            stability_comparisons += 1
            if previous_top == current_top:
                stable_top_count += 1
            else:
                top_lineage_changes += 1
        previous_top = current_top

        for scenario in ranked:
            if (
                scenario.scenario_status is ScenarioStatus.ACTIVE
                and scenario.scenario_lineage_key not in seen_active_lineages
            ):
                builder = _ProgressionEventBuilder(scenario=scenario, observations=[])
                builders.append(builder)
                open_builders.append(builder)
                seen_active_lineages.add(scenario.scenario_lineage_key)

    if final_snapshot is None:
        raise ValueError("validated source series unexpectedly produced no replay")
    delays = _pivot_delays(bars, final_snapshot)
    fractals = detect_causal_five_bar_fractals(bars)
    matured_counts, primary_outcomes, primary_records = _label_events(tuple(builders))
    anomalies: list[str] = []
    if not delays:
        anomalies.append("NO_CONFIRMED_PIVOTS")
    if not builders:
        anomalies.append("NO_ACTIVE_PROGRESSION_EVENTS")
    if not primary_records:
        anomalies.append("NO_MATURED_20_BAR_LABELS")
    if loaded.source_exclusions:
        anomalies.append("SOURCE_REFERENCE_OBSERVATIONS_EXCLUDED")
    analysis_seconds = time.perf_counter() - started
    result = SeriesResearchResult(
        ts_code=loaded.ts_code,
        freq=loaded.freq,
        bar_count=len(bars),
        trade_date_count=loaded.observed_trade_date_count,
        first_bar_at=loaded.first_bar_at,
        last_bar_at=loaded.last_bar_at,
        source_exclusion_count=len(loaded.source_exclusions),
        source_exclusion_reasons=tuple(
            sorted(
                Counter(item.reason_code for item in loaded.source_exclusions).items()
            )
        ),
        confirmed_pivot_count=len(delays),
        pivot_density_per_100_bars=len(delays) * 100 / len(bars),
        pivot_confirmation_delay_mean_bars=(
            statistics.mean(delays) if delays else None
        ),
        pivot_confirmation_delay_median_bars=(
            statistics.median(delays) if delays else None
        ),
        fractal_pivot_count=len(fractals),
        fractal_density_per_100_bars=len(fractals) * 100 / len(bars),
        fractal_confirmation_delay_bars=2,
        scenario_snapshot_count=scenario_snapshot_count,
        unique_scenario_count=len(scenario_keys),
        unique_lineage_count=len(lineage_keys),
        active_event_count=len(builders),
        empty_scenario_bar_count=empty_scenario_bars,
        top_lineage_stability_rate=(
            stable_top_count / stability_comparisons if stability_comparisons else None
        ),
        top_lineage_change_count=top_lineage_changes,
        matured_label_counts=matured_counts,
        outcome_counts_20_bar=primary_outcomes,
        source_load_seconds=0.0,
        analysis_seconds=analysis_seconds,
        peak_memory_bytes=0,
        anomalies=tuple(anomalies),
    )
    return SeriesAnalysis(result=result, primary_records=primary_records)


def _json_default(value: object) -> object:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "value"):
        return getattr(value, "value")
    raise TypeError(f"cannot encode {type(value).__name__}")


def _frequency_summary(
    freq: str, results: tuple[SeriesResearchResult, ...]
) -> dict[str, object]:
    selected = tuple(item for item in results if item.freq == freq)
    return {
        "series_count": len(selected),
        "bar_count": sum(item.bar_count for item in selected),
        "confirmed_pivot_count": sum(item.confirmed_pivot_count for item in selected),
        "fractal_pivot_count": sum(item.fractal_pivot_count for item in selected),
        "active_event_count": sum(item.active_event_count for item in selected),
        "matured_20_bar_label_count": sum(
            dict(item.matured_label_counts).get(20, 0) for item in selected
        ),
        "analysis_seconds": sum(item.analysis_seconds for item in selected),
        "max_peak_memory_bytes": max(
            (item.peak_memory_bytes for item in selected), default=0
        ),
        "anomaly_count": sum(len(item.anomalies) for item in selected),
    }


def _process_peak_memory_bytes() -> int:
    peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return peak * 1024 if sys.platform.startswith("linux") else peak


def run_readonly_validation(
    *,
    lake_root: Path,
    codes: tuple[str, ...],
    frequencies: tuple[str, ...],
    as_of: datetime,
    max_series_seconds: float = 30.0,
    max_peak_memory_bytes: int = 512 * 1024 * 1024,
) -> dict[str, object]:
    unknown_codes = set(codes).difference(MAJOR_INDEX_RESEARCH_CODES)
    unknown_frequencies = set(frequencies).difference(SUPPORTED_RESEARCH_FREQUENCIES)
    if unknown_codes:
        raise ValueError(f"unsupported codes: {sorted(unknown_codes)}")
    if unknown_frequencies:
        raise ValueError(f"unsupported frequencies: {sorted(unknown_frequencies)}")
    local_as_of = as_of.astimezone(ZoneInfo("Asia/Shanghai"))
    manifests: dict[str, SourceManifest] = {
        freq: build_source_manifest(
            lake_root=lake_root,
            freq=freq,
            visible_through=local_as_of.date(),
        )
        for freq in frequencies
    }
    results: list[SeriesResearchResult] = []
    failures: list[SeriesFailure] = []
    records_by_frequency: dict[str, list[ResearchOutcomeRecord]] = {
        freq: [] for freq in frequencies
    }
    for freq in frequencies:
        for ts_code in codes:
            series_started = time.perf_counter()
            load_started = time.perf_counter()
            with IndexWaveLakeReader(lake_root) as reader:
                loaded = reader.load_series(
                    ts_code=ts_code,
                    freq=freq,
                    as_of=local_as_of,
                    manifest=manifests[freq],
                )
            load_seconds = time.perf_counter() - load_started
            try:
                analysis = analyze_loaded_series(loaded)
            except WaveReplayFailure as exc:
                detail = str(exc.__cause__ or exc)
                failures.append(
                    SeriesFailure(
                        ts_code=loaded.ts_code,
                        freq=loaded.freq,
                        bar_count=len(loaded.bars),
                        first_bar_at=loaded.first_bar_at,
                        last_bar_at=loaded.last_bar_at,
                        reason_code=(
                            "SWING_PRICE_DIRECTION_CONTRADICTION"
                            if "swing must end" in detail
                            else "WAVE_REPLAY_CONTRACT_FAILURE"
                        ),
                        detail=detail,
                    )
                )
                del loaded
                gc.collect()
                continue
            peak_memory = _process_peak_memory_bytes()
            elapsed = time.perf_counter() - series_started
            result = replace(
                analysis.result,
                source_load_seconds=load_seconds,
                peak_memory_bytes=peak_memory,
            )
            if elapsed > max_series_seconds:
                raise RuntimeError(
                    f"SERIES_TIME_BUDGET_EXCEEDED: {ts_code}/{freq} took {elapsed:.3f}s"
                )
            if peak_memory > max_peak_memory_bytes:
                raise RuntimeError(
                    f"SERIES_MEMORY_BUDGET_EXCEEDED: {ts_code}/{freq} used {peak_memory} bytes"
                )
            results.append(result)
            records_by_frequency[freq].extend(analysis.primary_records)
            del loaded, analysis
            gc.collect()
    calibration: dict[str, CalibrationAudit] = {
        freq: run_calibration_audit(records_by_frequency[freq]) for freq in frequencies
    }
    materialized_results = tuple(results)
    failure_counts = Counter(item.freq for item in failures)
    return {
        "runner_version": RESEARCH_RUNNER_VERSION,
        "as_of": local_as_of,
        "lake_root": lake_root,
        "codes": codes,
        "frequencies": frequencies,
        "detector_profile": CAUSAL_ATR_PROFILE.detector_profile_key,
        "degree_profile": BASE_DEGREE_PROFILE.degree_key,
        "comparison_detector": COMPARISON_DETECTOR_VERSION,
        "manifests": {key: asdict(value) for key, value in manifests.items()},
        "series": [asdict(item) for item in materialized_results],
        "series_failures": [asdict(item) for item in failures],
        "frequency_summary": {
            freq: {
                **_frequency_summary(freq, materialized_results),
                "failure_count": failure_counts[freq],
            }
            for freq in frequencies
        },
        "calibration": {key: asdict(value) for key, value in calibration.items()},
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", required=True, type=datetime.fromisoformat)
    parser.add_argument("--lake-root", type=Path, default=DEFAULT_LAKE_ROOT)
    parser.add_argument(
        "--codes", default=",".join(MAJOR_INDEX_RESEARCH_CODES), help="comma list"
    )
    parser.add_argument(
        "--frequencies",
        default=",".join(SUPPORTED_RESEARCH_FREQUENCIES),
        help="comma list",
    )
    parser.add_argument("--max-series-seconds", type=float, default=30.0)
    parser.add_argument("--max-peak-memory-bytes", type=int, default=512 * 1024 * 1024)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = run_readonly_validation(
        lake_root=args.lake_root,
        codes=tuple(item for item in args.codes.split(",") if item),
        frequencies=tuple(item for item in args.frequencies.split(",") if item),
        as_of=args.as_of,
        max_series_seconds=args.max_series_seconds,
        max_peak_memory_bytes=args.max_peak_memory_bytes,
    )
    print(json.dumps(result, default=_json_default, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
