from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from scripts.research.sector_radar_backtest import (
    BASELINES,
    TOP_LIST_PERCENTILE,
    SignalEvent,
    build_daily_facts,
    build_signal_events,
    build_states,
    common_evaluation_dates,
    load_observations,
    split_phases,
)


EXPERIMENT_ID = "sector-radar-dc-l1-signal-grid-v2"
SIGNAL_LEVELS = (55.0, 60.0, 65.0, 70.0)
RESET_DISTANCE = 10.0


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


def _metric(values: Sequence[bool], baseline_rate: float | None) -> dict[str, float | int | list[float] | None]:
    successes = sum(values)
    sample_size = len(values)
    rate = successes / sample_size if sample_size else None
    return {
        "successes": successes,
        "sample_size": sample_size,
        "rate": rate,
        "ci95": _wilson_interval(successes, sample_size),
        "lift": (
            rate / baseline_rate
            if rate is not None and baseline_rate not in (None, 0)
            else None
        ),
    }


def _future_ranks(
    dates: Sequence[date],
    facts,
    current_date: date,
    sector_code: str,
) -> list[float] | None:
    date_index = {value: index for index, value in enumerate(dates)}
    index = date_index[current_date]
    if index + 5 >= len(dates):
        return None
    ranks: list[float] = []
    for offset in range(1, 6):
        fact = facts[dates[index + offset]].get(sector_code)
        if fact is None or fact.horizontal_rank_pct is None:
            return None
        ranks.append(float(fact.horizontal_rank_pct))
    return ranks


def _outcomes_from_ranks(ranks: Sequence[float]) -> dict[str, bool]:
    return {
        "entry_within_1d": ranks[0] >= TOP_LIST_PERCENTILE,
        "entry_within_3d": any(rank >= TOP_LIST_PERCENTILE for rank in ranks[:3]),
        "entry_within_5d": any(rank >= TOP_LIST_PERCENTILE for rank in ranks[:5]),
        "majority_1d": ranks[0] >= TOP_LIST_PERCENTILE,
        "majority_3d": sum(rank >= TOP_LIST_PERCENTILE for rank in ranks[:3]) >= 2,
        "majority_5d": sum(rank >= TOP_LIST_PERCENTILE for rank in ranks[:5]) >= 3,
    }


def build_conditional_baselines(dates, facts, phase_by_date):
    values = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for current_date, phase in phase_by_date.items():
        for sector_code, fact in facts[current_date].items():
            if fact.horizontal_rank_pct is None:
                continue
            ranks = _future_ranks(dates, facts, current_date, sector_code)
            if ranks is None:
                continue
            event_type = "retention" if fact.horizontal_rank_pct >= TOP_LIST_PERCENTILE else "early"
            outcomes = _outcomes_from_ranks(ranks)
            for metric_name, outcome in outcomes.items():
                values[phase][event_type][metric_name].append(outcome)
                values["all"][event_type][metric_name].append(outcome)

    result = {}
    for phase, phase_values in values.items():
        result[phase] = {}
        for event_type, event_values in phase_values.items():
            result[phase][event_type] = {
                metric_name: sum(metric_values) / len(metric_values)
                for metric_name, metric_values in event_values.items()
                if metric_values
            }
            result[phase][event_type]["candidate_days"] = len(
                event_values.get("majority_1d", ())
            )
    return result


def summarize_event_group(
    events: Sequence[SignalEvent],
    event_type: str,
    baseline_rates: Mapping[str, float],
) -> dict[str, object]:
    selected = [event for event in events if event.entry_type == event_type]
    if event_type == "entry":
        outcomes = {
            "entry_within_1d": [event.future_1d_rank_pct >= TOP_LIST_PERCENTILE for event in selected],
            "entry_within_3d": [event.future_3d_on_list_days >= 1 for event in selected],
            "entry_within_5d": [event.future_5d_on_list_days >= 1 for event in selected],
            "majority_3d": [event.success_3d for event in selected],
            "majority_5d": [event.success_5d for event in selected],
        }
    else:
        outcomes = {
            "majority_1d": [event.success_1d for event in selected],
            "majority_3d": [event.success_3d for event in selected],
            "majority_5d": [event.success_5d for event in selected],
        }
    sector_counts = Counter(f"{event.sector_code}|{event.sector_name}" for event in selected)
    return {
        "event_count": len(selected),
        "unique_sectors": len(sector_counts),
        "unique_dates": len({event.trade_date for event in selected}),
        "max_sector_event_share": (
            max(sector_counts.values()) / len(selected) if selected else None
        ),
        "sector_event_counts": dict(
            sorted(sector_counts.items(), key=lambda item: (-item[1], item[0]))
        ),
        "metrics": {
            metric_name: _metric(metric_values, baseline_rates.get(metric_name))
            for metric_name, metric_values in outcomes.items()
        },
    }


def build_grid_summary(
    input_csv: Path,
    *,
    expected_sector_count: int = 31,
) -> dict[str, object]:
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

    reference_states = {
        baseline: build_states(dates, facts, baseline)
        for baseline in BASELINES
    }
    evaluation_dates = common_evaluation_dates(dates, reference_states)
    phase_by_date, phase_bounds = split_phases(evaluation_dates)
    conditional_baselines = build_conditional_baselines(dates, facts, phase_by_date)

    grid = {}
    for baseline in BASELINES:
        baseline_grid = {}
        for signal_level in SIGNAL_LEVELS:
            states = build_states(
                dates,
                facts,
                baseline,
                signal_level=signal_level,
                reset_level=signal_level - RESET_DISTANCE,
            )
            events = build_signal_events(
                dates,
                rows_by_date,
                facts,
                {baseline: states},
                phase_by_date,
            )
            threshold_result = {}
            for phase in ("research", "calibration", "holdout", "all"):
                phase_events = [event for event in events if phase == "all" or event.phase == phase]
                threshold_result[phase] = {
                    "early": summarize_event_group(
                        phase_events,
                        "entry",
                        conditional_baselines[phase]["early"],
                    ),
                    "retention": summarize_event_group(
                        phase_events,
                        "retention",
                        conditional_baselines[phase]["retention"],
                    ),
                }
            baseline_grid[str(int(signal_level))] = threshold_result
        grid[str(baseline)] = baseline_grid

    return {
        "experiment_id": EXPERIMENT_ID,
        "input": {
            "sha256": input_hash,
            "start_date": dates[0].isoformat(),
            "end_date": dates[-1].isoformat(),
            "source_trading_days": len(source_dates),
            "valid_published_days": len(dates),
            "excluded_incomplete_dates": {
                current_date.isoformat(): count
                for current_date, count in sorted(excluded_dates.items())
            },
        },
        "config": {
            "baselines": list(BASELINES),
            "signal_levels": [int(level) for level in SIGNAL_LEVELS],
            "reset_distance": RESET_DISTANCE,
            "event_types": ["early", "retention"],
            "holdout_status": "exploratory_only_due_to_prior_full-window_review",
        },
        "phase_bounds": {
            phase: {"start": bounds[0].isoformat(), "end": bounds[1].isoformat()}
            for phase, bounds in phase_bounds.items()
        },
        "conditional_baselines": conditional_baselines,
        "grid": grid,
    }


def write_report(output_dir: Path, summary: Mapping[str, object]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# 板块雷达第二轮信号阈值对照",
        "",
        "- 固定：60/120 日基线、价格/成交等权、lambda=0.30、10 日趋势。",
        "- 对照：状态向上穿越 55/60/65/70，重置位固定低 10 分。",
        "- early：信号日尚未进入前 20%；retention：信号日已经进入前 20%。",
        "- 第二轮完整窗口已经在上一轮被查看，只用于产生下一版假设，不作为新样本外证明。",
        "",
        "## 全窗口提前转热",
        "",
        "| 基线 | 阈值 | 事件数 | 3日内上榜 | Lift | 5日内上榜 | Lift | 5日多数上榜 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for baseline in BASELINES:
        for level in SIGNAL_LEVELS:
            early = summary["grid"][str(baseline)][str(int(level))]["all"]["early"]
            metrics = early["metrics"]
            def fmt(value):
                return "--" if value is None else f"{value:.1%}"
            def fmt_lift(value):
                return "--" if value is None else f"{value:.2f}x"
            lines.append(
                f"| {baseline} | {int(level)} | {early['event_count']} | "
                f"{fmt(metrics['entry_within_3d']['rate'])} | {fmt_lift(metrics['entry_within_3d']['lift'])} | "
                f"{fmt(metrics['entry_within_5d']['rate'])} | {fmt_lift(metrics['entry_within_5d']['lift'])} | "
                f"{fmt(metrics['majority_5d']['rate'])} |"
            )
    lines.extend(
        [
            "",
            "## 全窗口高位延续",
            "",
            "| 基线 | 阈值 | 事件数 | 次日留榜 | 3日多数留榜 | 5日多数留榜 |",
            "|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for baseline in BASELINES:
        for level in SIGNAL_LEVELS:
            retention = summary["grid"][str(baseline)][str(int(level))]["all"]["retention"]
            metrics = retention["metrics"]
            def fmt(value):
                return "--" if value is None else f"{value:.1%}"
            lines.append(
                f"| {baseline} | {int(level)} | {retention['event_count']} | "
                f"{fmt(metrics['majority_1d']['rate'])} | "
                f"{fmt(metrics['majority_3d']['rate'])} | "
                f"{fmt(metrics['majority_5d']['rate'])} |"
            )
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(input_csv: Path, output_dir: Path) -> dict[str, object]:
    summary = build_grid_summary(input_csv)
    write_report(output_dir, summary)
    return summary


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the fixed sector-radar signal threshold grid")
    parser.add_argument("--input-csv", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(list(argv) if argv is not None else None)
    summary = run(args.input_csv, args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
