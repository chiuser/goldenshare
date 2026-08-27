from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from scripts.research.sector_radar_backtest import (
    BASELINES,
    TOP_LIST_PERCENTILE,
    Observation,
    SignalEvent,
    StatePoint,
    build_daily_facts,
    build_signal_events,
    build_states,
    common_evaluation_dates,
    is_turn_hot_signal,
    load_observations,
    percentile_ranks,
    split_phases,
)
from scripts.research.sector_radar_signal_grid import build_conditional_baselines


EXPERIMENT_ID = "sector-radar-dc-l1-robustness-v3"
EXPECTED_SECTOR_COUNT = 31
RESET_DISTANCE = 10.0


@dataclass(frozen=True)
class CandidateConfig:
    candidate_id: str
    baseline: int
    signal_level: float
    event_type: str
    role: str


CANDIDATES = (
    CandidateConfig("early_b60_t55", 60, 55.0, "early", "main"),
    CandidateConfig("early_b120_t55", 120, 55.0, "early", "main"),
    CandidateConfig("early_b60_t60", 60, 60.0, "early", "strict_secondary"),
    CandidateConfig("early_b120_t60", 120, 60.0, "early", "strict_secondary"),
    CandidateConfig("retention_b60_t70", 60, 70.0, "retention", "retention"),
    CandidateConfig("retention_b120_t70", 120, 70.0, "retention", "retention"),
)


@dataclass(frozen=True)
class OutcomeRecord:
    trade_date: date
    sector_code: str
    sector_name: str
    event_type: str
    outcomes: Mapping[str, bool]


@dataclass(frozen=True)
class MatchedPair:
    signal: OutcomeRecord
    control: OutcomeRecord
    year_distance: int
    trading_day_distance: int
    environment_distance: float


def metric_names(event_type: str) -> tuple[str, ...]:
    if event_type == "early":
        return (
            "entry_within_1d",
            "entry_within_3d",
            "entry_within_5d",
            "majority_3d",
            "majority_5d",
        )
    if event_type == "retention":
        return ("majority_1d", "majority_3d", "majority_5d")
    raise ValueError(f"unsupported event type: {event_type}")


def _wilson_interval(successes: int, sample_size: int) -> list[float] | None:
    if sample_size == 0:
        return None
    probability = successes / sample_size
    z = 1.959963984540054
    denominator = 1.0 + z * z / sample_size
    center = (probability + z * z / (2.0 * sample_size)) / denominator
    margin = (
        z
        * math.sqrt(
            probability * (1.0 - probability) / sample_size
            + z * z / (4.0 * sample_size * sample_size)
        )
        / denominator
    )
    return [max(0.0, center - margin), min(1.0, center + margin)]


def _rate(values: Sequence[bool], baseline_rate: float | None = None) -> dict[str, object]:
    sample_size = len(values)
    successes = sum(values)
    rate = successes / sample_size if sample_size else None
    interval = _wilson_interval(successes, sample_size)
    lift = rate / baseline_rate if rate is not None and baseline_rate not in (None, 0) else None
    lift_interval = (
        [interval[0] / baseline_rate, interval[1] / baseline_rate]
        if interval is not None and baseline_rate not in (None, 0)
        else None
    )
    return {
        "successes": successes,
        "sample_size": sample_size,
        "rate": rate,
        "ci95": interval,
        "lift": lift,
        "lift_ci95_vs_fixed_baseline": lift_interval,
    }


def _future_outcomes(
    dates: Sequence[date],
    date_index: Mapping[date, int],
    facts,
    current_date: date,
    sector_code: str,
) -> dict[str, bool] | None:
    index = date_index[current_date]
    if index + 5 >= len(dates):
        return None
    future = [facts[dates[index + offset]].get(sector_code) for offset in range(1, 6)]
    if any(item is None or item.horizontal_rank_pct is None for item in future):
        return None
    ranks = [float(item.horizontal_rank_pct) for item in future if item is not None]
    return {
        "entry_within_1d": ranks[0] >= TOP_LIST_PERCENTILE,
        "entry_within_3d": any(rank >= TOP_LIST_PERCENTILE for rank in ranks[:3]),
        "entry_within_5d": any(rank >= TOP_LIST_PERCENTILE for rank in ranks),
        "majority_1d": ranks[0] >= TOP_LIST_PERCENTILE,
        "majority_3d": sum(rank >= TOP_LIST_PERCENTILE for rank in ranks[:3]) >= 2,
        "majority_5d": sum(rank >= TOP_LIST_PERCENTILE for rank in ranks) >= 3,
    }


def _signal_record(event: SignalEvent) -> OutcomeRecord:
    return OutcomeRecord(
        trade_date=event.trade_date,
        sector_code=event.sector_code,
        sector_name=event.sector_name,
        event_type="retention" if event.entry_type == "retention" else "early",
        outcomes={
            "entry_within_1d": event.future_1d_rank_pct >= TOP_LIST_PERCENTILE,
            "entry_within_3d": event.future_3d_on_list_days >= 1,
            "entry_within_5d": event.future_5d_on_list_days >= 1,
            "majority_1d": event.success_1d,
            "majority_3d": event.success_3d,
            "majority_5d": event.success_5d,
        },
    )


def build_sector_day_records(
    dates: Sequence[date],
    evaluation_dates: Sequence[date],
    rows_by_date: Mapping[date, Mapping[str, Observation]],
    facts,
) -> dict[tuple[date, str], OutcomeRecord]:
    date_index = {value: index for index, value in enumerate(dates)}
    records: dict[tuple[date, str], OutcomeRecord] = {}
    for current_date in evaluation_dates:
        for sector_code, fact in facts[current_date].items():
            if fact.horizontal_rank_pct is None:
                continue
            outcomes = _future_outcomes(dates, date_index, facts, current_date, sector_code)
            row = rows_by_date[current_date].get(sector_code)
            if outcomes is None or row is None:
                continue
            event_type = (
                "retention"
                if fact.horizontal_rank_pct >= TOP_LIST_PERCENTILE
                else "early"
            )
            records[(current_date, sector_code)] = OutcomeRecord(
                trade_date=current_date,
                sector_code=sector_code,
                sector_name=row.sector_name,
                event_type=event_type,
                outcomes=outcomes,
            )
    return records


def build_market_environment(
    evaluation_dates: Sequence[date],
    rows_by_date: Mapping[date, Mapping[str, Observation]],
) -> dict[date, tuple[float, float]]:
    medians: dict[str, float] = {}
    dispersions: dict[str, float] = {}
    for current_date in evaluation_dates:
        returns = [row.pct_change for row in rows_by_date[current_date].values()]
        center = float(statistics.median(returns))
        dispersion = float(statistics.median(abs(value - center) for value in returns))
        key = current_date.isoformat()
        medians[key] = center
        dispersions[key] = dispersion
    median_percentiles = percentile_ranks(medians)
    dispersion_percentiles = percentile_ranks(dispersions)
    return {
        current_date: (
            median_percentiles[current_date.isoformat()],
            dispersion_percentiles[current_date.isoformat()],
        )
        for current_date in evaluation_dates
    }


def build_matched_controls(
    signals: Sequence[OutcomeRecord],
    sector_day_records: Mapping[tuple[date, str], OutcomeRecord],
    environment: Mapping[date, tuple[float, float]],
    evaluation_dates: Sequence[date],
) -> list[MatchedPair]:
    date_position = {value: index for index, value in enumerate(evaluation_dates)}
    signal_keys = {(record.trade_date, record.sector_code) for record in signals}
    used_controls: set[tuple[date, str]] = set()
    pairs: list[MatchedPair] = []
    for signal in sorted(signals, key=lambda item: (item.trade_date, item.sector_code)):
        signal_environment = environment[signal.trade_date]
        candidates = []
        for key, control in sector_day_records.items():
            if (
                key in signal_keys
                or key in used_controls
                or control.sector_code != signal.sector_code
                or control.event_type != signal.event_type
            ):
                continue
            control_environment = environment[control.trade_date]
            year_distance = abs(control.trade_date.year - signal.trade_date.year)
            environment_distance = (
                abs(control_environment[0] - signal_environment[0])
                + abs(control_environment[1] - signal_environment[1])
            )
            trading_day_distance = abs(
                date_position[control.trade_date] - date_position[signal.trade_date]
            )
            candidates.append(
                (
                    year_distance,
                    environment_distance,
                    trading_day_distance,
                    control.trade_date,
                    key,
                    control,
                )
            )
        if not candidates:
            continue
        best = min(candidates)
        used_controls.add(best[4])
        pairs.append(
            MatchedPair(
                signal=signal,
                control=best[5],
                year_distance=best[0],
                environment_distance=best[1],
                trading_day_distance=best[2],
            )
        )
    return pairs


def _comparison(
    signals: Sequence[OutcomeRecord],
    controls: Sequence[OutcomeRecord],
    event_type: str,
) -> dict[str, object]:
    result: dict[str, object] = {}
    for metric in metric_names(event_type):
        signal_metric = _rate([record.outcomes[metric] for record in signals])
        control_metric = _rate([record.outcomes[metric] for record in controls])
        signal_rate = signal_metric["rate"]
        control_rate = control_metric["rate"]
        lift = (
            float(signal_rate) / float(control_rate)
            if signal_rate is not None and control_rate not in (None, 0)
            else None
        )
        signal_ci = signal_metric["ci95"]
        control_ci = control_metric["ci95"]
        lift_ci = None
        if signal_ci is not None and control_ci is not None and control_ci[0] > 0:
            lift_ci = [signal_ci[0] / control_ci[1], signal_ci[1] / control_ci[0]]
        result[metric] = {
            "signal": signal_metric,
            "control": control_metric,
            "lift": lift,
            "lift_ci95_conservative_wilson_ratio": lift_ci,
        }
    return result


def summarize_matched_pairs(pairs: Sequence[MatchedPair], event_type: str) -> dict[str, object]:
    return {
        "pair_count": len(pairs),
        "match_quality": {
            "same_year_share": (
                sum(pair.year_distance == 0 for pair in pairs) / len(pairs) if pairs else None
            ),
            "median_trading_day_distance": (
                float(statistics.median(pair.trading_day_distance for pair in pairs))
                if pairs
                else None
            ),
            "median_environment_percentile_distance": (
                float(statistics.median(pair.environment_distance for pair in pairs))
                if pairs
                else None
            ),
        },
        "metrics": _comparison(
            [pair.signal for pair in pairs],
            [pair.control for pair in pairs],
            event_type,
        ),
    }


def _quarter(current_date: date) -> str:
    return f"{current_date.year}-Q{(current_date.month - 1) // 3 + 1}"


def summarize_quarters(pairs: Sequence[MatchedPair], event_type: str) -> dict[str, object]:
    by_quarter: dict[str, list[MatchedPair]] = defaultdict(list)
    for pair in pairs:
        by_quarter[_quarter(pair.signal.trade_date)].append(pair)
    return {
        quarter: {
            "pair_count": len(selected),
            "metrics": _comparison(
                [pair.signal for pair in selected],
                [pair.control for pair in selected],
                event_type,
            ),
        }
        for quarter, selected in sorted(by_quarter.items())
    }


def summarize_leave_one_sector_out(
    pairs: Sequence[MatchedPair],
    event_type: str,
    sectors: Sequence[str],
) -> dict[str, object]:
    by_sector: dict[str, object] = {}
    for sector_code in sorted(sectors):
        selected = [pair for pair in pairs if pair.signal.sector_code != sector_code]
        by_sector[sector_code] = {
            "pair_count": len(selected),
            "metrics": _comparison(
                [pair.signal for pair in selected],
                [pair.control for pair in selected],
                event_type,
            ),
        }
    ranges: dict[str, object] = {}
    for metric in metric_names(event_type):
        lifts = [
            result["metrics"][metric]["lift"]
            for result in by_sector.values()
            if result["metrics"][metric]["lift"] is not None
        ]
        ranges[metric] = {
            "min_lift": min(lifts) if lifts else None,
            "max_lift": max(lifts) if lifts else None,
            "direction_above_one_share": (
                sum(value > 1.0 for value in lifts) / len(lifts) if lifts else None
            ),
        }
    return {
        "excluded_sector_count": len(by_sector),
        "ranges": ranges,
        "by_excluded_sector": by_sector,
    }


def build_unsmoothed_states(
    dates: Sequence[date],
    smoothed_states: Mapping[date, Mapping[str, StatePoint]],
    *,
    signal_level: float,
    reset_level: float,
) -> dict[date, dict[str, StatePoint]]:
    result: dict[date, dict[str, StatePoint]] = defaultdict(dict)
    histories: dict[str, list[tuple[date, float]]] = defaultdict(list)
    armed: dict[str, bool] = defaultdict(lambda: True)
    date_position = {value: index for index, value in enumerate(dates)}
    for current_date in dates:
        for sector_code, point in smoothed_states.get(current_date, {}).items():
            history = histories[sector_code]
            if history:
                current_index = date_position[current_date]
                if current_index == 0 or history[-1][0] != dates[current_index - 1]:
                    history.clear()
                    armed[sector_code] = True
            candidate_values = [item[1] for item in history[-9:]] + [point.state_input]
            signal = is_turn_hot_signal(
                candidate_values,
                armed=armed[sector_code],
                signal_level=signal_level,
            )
            if signal:
                armed[sector_code] = False
            if point.state_input < reset_level:
                armed[sector_code] = True
            history.append((current_date, point.state_input))
            result[current_date][sector_code] = StatePoint(
                state_input=point.state_input,
                heat_state=point.state_input,
                signal=signal,
            )
    return dict(result)


def build_daily_rule_records(
    rule: str,
    dates: Sequence[date],
    evaluation_dates: Sequence[date],
    sector_day_records: Mapping[tuple[date, str], OutcomeRecord],
    facts,
    event_type: str,
) -> list[OutcomeRecord]:
    records: list[OutcomeRecord] = []
    for current_date in evaluation_dates:
        if rule == "daily_relative_return_top20":
            values = {
                code: fact.relative_return
                for code, fact in facts[current_date].items()
                if fact.horizontal_rank_pct is not None
            }
        elif rule == "daily_amount_activity_top20":
            values = {
                code: float(fact.log_amount_ratio_20)
                for code, fact in facts[current_date].items()
                if fact.log_amount_ratio_20 is not None and fact.horizontal_rank_pct is not None
            }
        else:
            raise ValueError(f"unsupported daily rule: {rule}")
        ranks = percentile_ranks(values)
        for sector_code, rank in ranks.items():
            record = sector_day_records.get((current_date, sector_code))
            if record is not None and record.event_type == event_type and rank >= TOP_LIST_PERCENTILE:
                records.append(record)
    return records


def summarize_rule(
    records: Sequence[OutcomeRecord],
    event_type: str,
    natural_rates: Mapping[str, float],
) -> dict[str, object]:
    return {
        "event_count": len(records),
        "unique_sectors": len({record.sector_code for record in records}),
        "unique_dates": len({record.trade_date for record in records}),
        "metrics": {
            metric: _rate(
                [record.outcomes[metric] for record in records],
                natural_rates.get(metric),
            )
            for metric in metric_names(event_type)
        },
    }


def build_robustness_summary(
    input_csv: Path,
    *,
    expected_sector_count: int = EXPECTED_SECTOR_COUNT,
) -> tuple[dict[str, object], dict[str, list[MatchedPair]]]:
    source_dates, source_rows_by_date, input_hash = load_observations(input_csv)
    if max(len(rows) for rows in source_rows_by_date.values()) != expected_sector_count:
        raise ValueError("input does not contain the expected 31-sector cohort")
    excluded_dates = {
        current_date: len(rows)
        for current_date, rows in source_rows_by_date.items()
        if len(rows) != expected_sector_count
    }
    dates = [current_date for current_date in source_dates if current_date not in excluded_dates]
    rows_by_date = {current_date: source_rows_by_date[current_date] for current_date in dates}
    facts = build_daily_facts(dates, rows_by_date)
    reference_states = {baseline: build_states(dates, facts, baseline) for baseline in BASELINES}
    evaluation_dates = common_evaluation_dates(dates, reference_states)
    phase_by_date, _ = split_phases(evaluation_dates)
    conditional_baselines = build_conditional_baselines(dates, facts, phase_by_date)
    sector_day_records = build_sector_day_records(
        dates,
        evaluation_dates,
        rows_by_date,
        facts,
    )
    environment = build_market_environment(evaluation_dates, rows_by_date)
    sectors = sorted({code for rows in rows_by_date.values() for code in rows})

    candidates: dict[str, object] = {}
    matched_pairs: dict[str, list[MatchedPair]] = {}
    for config in CANDIDATES:
        states = build_states(
            dates,
            facts,
            config.baseline,
            signal_level=config.signal_level,
            reset_level=config.signal_level - RESET_DISTANCE,
        )
        signal_events = build_signal_events(
            dates,
            rows_by_date,
            facts,
            {config.baseline: states},
            phase_by_date,
        )
        target_entry_type = "entry" if config.event_type == "early" else "retention"
        signal_records = [
            _signal_record(event)
            for event in signal_events
            if event.entry_type == target_entry_type
        ]
        pairs = build_matched_controls(
            signal_records,
            sector_day_records,
            environment,
            evaluation_dates,
        )
        matched_pairs[config.candidate_id] = pairs

        unsmoothed_states = build_unsmoothed_states(
            dates,
            states,
            signal_level=config.signal_level,
            reset_level=config.signal_level - RESET_DISTANCE,
        )
        unsmoothed_events = build_signal_events(
            dates,
            rows_by_date,
            facts,
            {config.baseline: unsmoothed_states},
            phase_by_date,
        )
        unsmoothed_records = [
            _signal_record(event)
            for event in unsmoothed_events
            if event.entry_type == target_entry_type
        ]
        natural_rates = conditional_baselines["all"][config.event_type]
        return_records = build_daily_rule_records(
            "daily_relative_return_top20",
            dates,
            evaluation_dates,
            sector_day_records,
            facts,
            config.event_type,
        )
        amount_records = build_daily_rule_records(
            "daily_amount_activity_top20",
            dates,
            evaluation_dates,
            sector_day_records,
            facts,
            config.event_type,
        )
        candidates[config.candidate_id] = {
            "config": {
                "baseline": config.baseline,
                "signal_level": int(config.signal_level),
                "reset_level": int(config.signal_level - RESET_DISTANCE),
                "event_type": config.event_type,
                "role": config.role,
            },
            "signal_event_count": len(signal_records),
            "matched_controls": summarize_matched_pairs(pairs, config.event_type),
            "quarterly_stability": summarize_quarters(pairs, config.event_type),
            "leave_one_sector_out": summarize_leave_one_sector_out(
                pairs,
                config.event_type,
                sectors,
            ),
            "simple_rule_counterexamples": {
                "complex_smoothed_signal": summarize_rule(
                    signal_records,
                    config.event_type,
                    natural_rates,
                ),
                "daily_relative_return_top20": summarize_rule(
                    return_records,
                    config.event_type,
                    natural_rates,
                ),
                "daily_amount_activity_top20": summarize_rule(
                    amount_records,
                    config.event_type,
                    natural_rates,
                ),
                "unsmoothed_state_signal": summarize_rule(
                    unsmoothed_records,
                    config.event_type,
                    natural_rates,
                ),
            },
        }

    return (
        {
            "experiment_id": EXPERIMENT_ID,
            "evidence_status": "historical_robustness_only_not_new_holdout",
            "input": {
                "sha256": input_hash,
                "start_date": dates[0].isoformat(),
                "end_date": dates[-1].isoformat(),
                "source_trading_days": len(source_dates),
                "valid_published_days": len(dates),
                "evaluation_days": len(evaluation_dates),
                "sector_count": expected_sector_count,
                "excluded_incomplete_dates": {
                    current_date.isoformat(): count
                    for current_date, count in sorted(excluded_dates.items())
                },
            },
            "config": {
                "candidates": [config.candidate_id for config in CANDIDATES],
                "matching": "same_sector_and_event_type_without_replacement",
                "matching_order": [
                    "year_distance",
                    "market_environment_percentile_distance",
                    "trading_day_distance",
                    "date",
                ],
                "time_block": "calendar_quarter",
                "simple_rules": [
                    "daily_relative_return_top20",
                    "daily_amount_activity_top20",
                    "unsmoothed_state_signal",
                ],
            },
            "candidates": candidates,
        },
        matched_pairs,
    )


def write_outputs(
    output_dir: Path,
    summary: Mapping[str, object],
    matched_pairs: Mapping[str, Sequence[MatchedPair]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with (output_dir / "matched-controls.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "candidate_id",
                "sector_code",
                "sector_name",
                "event_type",
                "signal_trade_date",
                "control_trade_date",
                "year_distance",
                "trading_day_distance",
                "environment_percentile_distance",
            ],
        )
        writer.writeheader()
        for candidate_id, pairs in matched_pairs.items():
            for pair in pairs:
                writer.writerow(
                    {
                        "candidate_id": candidate_id,
                        "sector_code": pair.signal.sector_code,
                        "sector_name": pair.signal.sector_name,
                        "event_type": pair.signal.event_type,
                        "signal_trade_date": pair.signal.trade_date.isoformat(),
                        "control_trade_date": pair.control.trade_date.isoformat(),
                        "year_distance": pair.year_distance,
                        "trading_day_distance": pair.trading_day_distance,
                        "environment_percentile_distance": f"{pair.environment_distance:.8f}",
                    }
                )


def run(input_csv: Path, output_dir: Path) -> dict[str, object]:
    summary, matched_pairs = build_robustness_summary(input_csv)
    write_outputs(output_dir, summary, matched_pairs)
    return summary


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the frozen sector-radar R1 robustness checks")
    parser.add_argument("--input-csv", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(list(argv) if argv is not None else None)
    summary = run(args.input_csv, args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
