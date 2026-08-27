from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping, Sequence


EXPERIMENT_ID = "sector-radar-dc-l1-b60-b120-v1"
BASELINES = (60, 120)
AMOUNT_WINDOW = 20
TREND_WINDOW = 10
LAMBDA = 0.30
Z_CLIP = 3.0
SIGNAL_LEVEL = 70.0
RESET_LEVEL = 60.0
UP_SHARE_MIN = 0.60
TOP_LIST_PERCENTILE = 80.0
BOOTSTRAP_BLOCK_DAYS = 20
BOOTSTRAP_SAMPLES = 2_000
BOOTSTRAP_CONFIDENCE = 0.95
RANDOM_SEED = 20_260_821


@dataclass(frozen=True)
class Observation:
    trade_date: date
    sector_code: str
    sector_name: str
    pct_change: float
    amount: float


@dataclass(frozen=True)
class DailyFact:
    relative_return: float
    amount_ratio_20: float | None
    log_amount_ratio_20: float | None
    horizontal_rank_pct: float | None


@dataclass(frozen=True)
class StatePoint:
    state_input: float
    heat_state: float
    signal: bool


@dataclass(frozen=True)
class SignalEvent:
    baseline: int
    trade_date: date
    sector_code: str
    sector_name: str
    phase: str
    signal_day_rank_pct: float
    entry_type: str
    success_1d: bool
    success_3d: bool
    success_5d: bool
    future_1d_rank_pct: float
    future_3d_on_list_days: int
    future_5d_on_list_days: int
    future_5d_relative_return_sum: float
    future_5d_amount_active_days: int


def _median(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("median requires at least one value")
    return float(statistics.median(values))


def _quantile(values: Sequence[float], probability: float) -> float:
    if not values:
        raise ValueError("quantile requires at least one value")
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return float(ordered[lower] * (1.0 - weight) + ordered[upper] * weight)


def robust_z(value: float, history: Sequence[float], *, clip: float = Z_CLIP) -> float | None:
    if not history:
        return None
    center = _median(history)
    mad = _median([abs(item - center) for item in history])
    if mad == 0:
        return None
    score = (value - center) / (1.4826 * mad)
    return max(-clip, min(clip, score))


def bounded_state_input(relative_z: float, amount_z: float) -> float:
    composite_z = 0.5 * relative_z + 0.5 * amount_z
    return max(0.0, min(100.0, 50.0 + composite_z / Z_CLIP * 50.0))


def percentile_ranks(values: Mapping[str, float]) -> dict[str, float]:
    if not values:
        return {}
    ordered = sorted(values.items(), key=lambda item: (item[1], item[0]))
    if len(ordered) == 1:
        return {ordered[0][0]: 50.0}

    ranks: dict[str, float] = {}
    index = 0
    while index < len(ordered):
        end = index
        while end + 1 < len(ordered) and ordered[end + 1][1] == ordered[index][1]:
            end += 1
        average_rank = (index + end) / 2.0
        percentile = average_rank / (len(ordered) - 1) * 100.0
        for cursor in range(index, end + 1):
            ranks[ordered[cursor][0]] = percentile
        index = end + 1
    return ranks


def linear_slope(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    x_mean = (len(values) - 1) / 2.0
    y_mean = sum(values) / len(values)
    numerator = sum((index - x_mean) * (value - y_mean) for index, value in enumerate(values))
    denominator = sum((index - x_mean) ** 2 for index in range(len(values)))
    return numerator / denominator if denominator else 0.0


def is_turn_hot_signal(
    states: Sequence[float],
    *,
    armed: bool,
    signal_level: float = SIGNAL_LEVEL,
) -> bool:
    if not armed or len(states) < TREND_WINDOW:
        return False
    current = states[-1]
    previous = states[-2]
    recent = states[-TREND_WINDOW:]
    upward_changes = sum(1 for left, right in zip(recent, recent[1:]) if right > left)
    upward_share = upward_changes / (TREND_WINDOW - 1)
    return (
        previous < signal_level <= current
        and linear_slope(recent) > 0
        and upward_share >= UP_SHARE_MIN
    )


def load_observations(path: Path) -> tuple[list[date], dict[date, dict[str, Observation]], str]:
    raw_bytes = path.read_bytes()
    rows_by_date: dict[date, dict[str, Observation]] = defaultdict(dict)
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        expected = {"trade_date", "sector_code", "sector_name", "pct_change", "amount"}
        if set(reader.fieldnames or ()) != expected:
            raise ValueError(f"unexpected columns: {reader.fieldnames}; expected {sorted(expected)}")
        for row in reader:
            trade_date = date.fromisoformat(row["trade_date"])
            sector_code = row["sector_code"].strip()
            sector_name = row["sector_name"].strip()
            if not sector_code or not sector_name:
                raise ValueError(f"blank sector identity at {trade_date}")
            key_rows = rows_by_date[trade_date]
            if sector_code in key_rows:
                raise ValueError(f"duplicate observation: {trade_date}/{sector_code}")
            pct_change = float(row["pct_change"])
            amount = float(row["amount"])
            if not math.isfinite(pct_change) or not math.isfinite(amount):
                raise ValueError(f"non-finite observation: {trade_date}/{sector_code}")
            key_rows[sector_code] = Observation(
                trade_date=trade_date,
                sector_code=sector_code,
                sector_name=sector_name,
                pct_change=pct_change,
                amount=amount,
            )
    dates = sorted(rows_by_date)
    if not dates:
        raise ValueError("input contains no observations")
    return dates, dict(rows_by_date), hashlib.sha256(raw_bytes).hexdigest()


def build_daily_facts(
    dates: Sequence[date],
    rows_by_date: Mapping[date, Mapping[str, Observation]],
) -> dict[date, dict[str, DailyFact]]:
    facts: dict[date, dict[str, DailyFact]] = {}
    amount_history: dict[str, list[tuple[date, float]]] = defaultdict(list)

    for current_date in dates:
        rows = rows_by_date[current_date]
        return_median = _median([row.pct_change for row in rows.values()])
        interim: dict[str, tuple[float, float | None, float | None]] = {}
        for code, row in rows.items():
            history = amount_history[code]
            amount_ratio: float | None = None
            log_amount_ratio: float | None = None
            if len(history) >= AMOUNT_WINDOW and row.amount > 0:
                expected_dates = dates[max(0, dates.index(current_date) - AMOUNT_WINDOW) : dates.index(current_date)]
                recent = history[-AMOUNT_WINDOW:]
                if [item[0] for item in recent] == list(expected_dates):
                    denominator = _median([item[1] for item in recent])
                    if denominator > 0:
                        amount_ratio = row.amount / denominator
                        if amount_ratio > 0:
                            log_amount_ratio = math.log(amount_ratio)
            interim[code] = (row.pct_change - return_median, amount_ratio, log_amount_ratio)

        valid_codes = {
            code
            for code, (_, amount_ratio, log_amount_ratio) in interim.items()
            if amount_ratio is not None and log_amount_ratio is not None
        }
        return_pct = percentile_ranks({code: interim[code][0] for code in valid_codes})
        amount_pct = percentile_ranks({code: interim[code][2] for code in valid_codes})
        horizontal_score = {
            code: 0.5 * return_pct[code] + 0.5 * amount_pct[code]
            for code in valid_codes
        }
        horizontal_rank = percentile_ranks(horizontal_score)

        facts[current_date] = {
            code: DailyFact(
                relative_return=relative_return,
                amount_ratio_20=amount_ratio,
                log_amount_ratio_20=log_amount_ratio,
                horizontal_rank_pct=horizontal_rank.get(code),
            )
            for code, (relative_return, amount_ratio, log_amount_ratio) in interim.items()
        }
        for code, row in rows.items():
            if row.amount > 0:
                amount_history[code].append((current_date, row.amount))
            else:
                amount_history[code].clear()
    return facts


def build_states(
    dates: Sequence[date],
    facts: Mapping[date, Mapping[str, DailyFact]],
    baseline: int,
    *,
    signal_level: float = SIGNAL_LEVEL,
    reset_level: float = RESET_LEVEL,
) -> dict[date, dict[str, StatePoint]]:
    states: dict[date, dict[str, StatePoint]] = defaultdict(dict)
    histories: dict[str, list[tuple[date, float, float]]] = defaultdict(list)
    state_history: dict[str, list[tuple[date, float]]] = defaultdict(list)
    armed: dict[str, bool] = defaultdict(lambda: True)

    for date_index, current_date in enumerate(dates):
        expected_history_dates = list(dates[max(0, date_index - baseline) : date_index])
        for code, fact in facts[current_date].items():
            if fact.log_amount_ratio_20 is None:
                histories[code].clear()
                state_history[code].clear()
                armed[code] = True
                continue
            history = histories[code]
            recent = history[-baseline:]
            if len(recent) < baseline or [item[0] for item in recent] != expected_history_dates:
                history.append((current_date, fact.relative_return, fact.log_amount_ratio_20))
                state_history[code].clear()
                armed[code] = True
                continue
            relative_z = robust_z(fact.relative_return, [item[1] for item in recent])
            amount_z = robust_z(fact.log_amount_ratio_20, [item[2] for item in recent])
            history.append((current_date, fact.relative_return, fact.log_amount_ratio_20))
            if relative_z is None or amount_z is None:
                state_history[code].clear()
                armed[code] = True
                continue

            state_input = bounded_state_input(relative_z, amount_z)
            previous_states = state_history[code]
            if previous_states and previous_states[-1][0] == dates[date_index - 1]:
                heat_state = LAMBDA * state_input + (1.0 - LAMBDA) * previous_states[-1][1]
            else:
                previous_states.clear()
                armed[code] = True
                heat_state = state_input
            candidate_states = [item[1] for item in previous_states[-(TREND_WINDOW - 1) :]] + [heat_state]
            signal = is_turn_hot_signal(
                candidate_states,
                armed=armed[code],
                signal_level=signal_level,
            )
            if signal:
                armed[code] = False
            if heat_state < reset_level:
                armed[code] = True
            previous_states.append((current_date, heat_state))
            states[current_date][code] = StatePoint(
                state_input=state_input,
                heat_state=heat_state,
                signal=signal,
            )
    return dict(states)


def _future_success(ranks: Sequence[float]) -> bool:
    required = (len(ranks) + 1) // 2
    return sum(rank >= TOP_LIST_PERCENTILE for rank in ranks) >= required


def common_evaluation_dates(
    dates: Sequence[date],
    states_by_baseline: Mapping[int, Mapping[date, Mapping[str, StatePoint]]],
) -> list[date]:
    return [
        current_date
        for index, current_date in enumerate(dates)
        if index + 5 < len(dates)
        and all(states_by_baseline[baseline].get(current_date) for baseline in BASELINES)
    ]


def split_phases(evaluation_dates: Sequence[date]) -> tuple[dict[date, str], dict[str, tuple[date, date]]]:
    if len(evaluation_dates) < 4:
        raise ValueError("not enough common evaluation dates for chronological split")
    research_end = max(1, int(len(evaluation_dates) * 0.50))
    calibration_end = max(research_end + 1, int(len(evaluation_dates) * 0.75))
    phase_dates = {
        "research": evaluation_dates[:research_end],
        "calibration": evaluation_dates[research_end:calibration_end],
        "holdout": evaluation_dates[calibration_end:],
    }
    if any(not values for values in phase_dates.values()):
        raise ValueError("chronological split produced an empty phase")
    mapping = {current_date: phase for phase, values in phase_dates.items() for current_date in values}
    bounds = {phase: (values[0], values[-1]) for phase, values in phase_dates.items()}
    return mapping, bounds


def build_signal_events(
    dates: Sequence[date],
    rows_by_date: Mapping[date, Mapping[str, Observation]],
    facts: Mapping[date, Mapping[str, DailyFact]],
    states_by_baseline: Mapping[int, Mapping[date, Mapping[str, StatePoint]]],
    phase_by_date: Mapping[date, str],
) -> list[SignalEvent]:
    date_index = {current_date: index for index, current_date in enumerate(dates)}
    events: list[SignalEvent] = []
    for baseline in sorted(states_by_baseline):
        for current_date, state_rows in states_by_baseline[baseline].items():
            phase = phase_by_date.get(current_date)
            if phase is None:
                continue
            index = date_index[current_date]
            for code, state in state_rows.items():
                if not state.signal:
                    continue
                current_fact = facts[current_date].get(code)
                current_row = rows_by_date[current_date].get(code)
                if current_fact is None or current_row is None or current_fact.horizontal_rank_pct is None:
                    continue
                future_facts = [facts[dates[index + offset]].get(code) for offset in range(1, 6)]
                if any(item is None or item.horizontal_rank_pct is None for item in future_facts):
                    continue
                typed_future = [item for item in future_facts if item is not None]
                ranks = [float(item.horizontal_rank_pct) for item in typed_future]
                events.append(
                    SignalEvent(
                        baseline=baseline,
                        trade_date=current_date,
                        sector_code=code,
                        sector_name=current_row.sector_name,
                        phase=phase,
                        signal_day_rank_pct=float(current_fact.horizontal_rank_pct),
                        entry_type=(
                            "retention"
                            if current_fact.horizontal_rank_pct >= TOP_LIST_PERCENTILE
                            else "entry"
                        ),
                        success_1d=_future_success(ranks[:1]),
                        success_3d=_future_success(ranks[:3]),
                        success_5d=_future_success(ranks[:5]),
                        future_1d_rank_pct=ranks[0],
                        future_3d_on_list_days=sum(rank >= TOP_LIST_PERCENTILE for rank in ranks[:3]),
                        future_5d_on_list_days=sum(rank >= TOP_LIST_PERCENTILE for rank in ranks),
                        future_5d_relative_return_sum=sum(item.relative_return for item in typed_future),
                        future_5d_amount_active_days=sum(
                            item.amount_ratio_20 is not None and item.amount_ratio_20 > 1.0
                            for item in typed_future
                        ),
                    )
                )
    return events


def _baseline_outcomes(
    dates: Sequence[date],
    facts: Mapping[date, Mapping[str, DailyFact]],
    phase_by_date: Mapping[date, str],
) -> dict[str, dict[str, float | int]]:
    date_index = {current_date: index for index, current_date in enumerate(dates)}
    outcomes: dict[str, dict[str, list[bool]]] = defaultdict(lambda: defaultdict(list))
    for current_date, phase in phase_by_date.items():
        index = date_index[current_date]
        for code, fact in facts[current_date].items():
            if fact.horizontal_rank_pct is None:
                continue
            future = [facts[dates[index + offset]].get(code) for offset in range(1, 6)]
            if any(item is None or item.horizontal_rank_pct is None for item in future):
                continue
            ranks = [float(item.horizontal_rank_pct) for item in future if item is not None]
            outcomes[phase]["success_1d"].append(_future_success(ranks[:1]))
            outcomes[phase]["success_3d"].append(_future_success(ranks[:3]))
            outcomes[phase]["success_5d"].append(_future_success(ranks[:5]))
    result: dict[str, dict[str, float | int]] = {}
    for phase, metrics in outcomes.items():
        phase_result: dict[str, float | int] = {"candidate_days": len(metrics["success_1d"])}
        for metric, values in metrics.items():
            phase_result[f"{metric}_rate"] = sum(values) / len(values) if values else 0.0
        result[phase] = phase_result
    return result


def _bootstrap_interval(events: Sequence[SignalEvent], field: str) -> tuple[float, float] | None:
    if not events:
        return None
    events_by_date: dict[date, list[SignalEvent]] = defaultdict(list)
    for event in events:
        events_by_date[event.trade_date].append(event)
    unique_dates = sorted(events_by_date)
    if len(unique_dates) < BOOTSTRAP_BLOCK_DAYS * 2:
        return None
    blocks = [unique_dates[index : index + BOOTSTRAP_BLOCK_DAYS] for index in range(0, len(unique_dates), BOOTSTRAP_BLOCK_DAYS)]
    rng = random.Random(RANDOM_SEED)
    samples: list[float] = []
    for _ in range(BOOTSTRAP_SAMPLES):
        sampled: list[SignalEvent] = []
        while len(sampled) < len(events):
            block = rng.choice(blocks)
            sampled.extend(event for block_date in block for event in events_by_date[block_date])
        sampled = sampled[: len(events)]
        samples.append(sum(bool(getattr(event, field)) for event in sampled) / len(sampled))
    tail = (1.0 - BOOTSTRAP_CONFIDENCE) / 2.0
    return _quantile(samples, tail), _quantile(samples, 1.0 - tail)


def _wilson_interval(events: Sequence[SignalEvent], field: str) -> tuple[float, float] | None:
    if not events:
        return None
    successes = sum(bool(getattr(event, field)) for event in events)
    sample_size = len(events)
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
    return max(0.0, center - margin), min(1.0, center + margin)


def _confidence_interval(
    events: Sequence[SignalEvent],
    field: str,
) -> tuple[tuple[float, float] | None, str | None]:
    interval = _bootstrap_interval(events, field)
    if interval is not None:
        return interval, "moving_block_bootstrap_20d"
    interval = _wilson_interval(events, field)
    return interval, "wilson_score_fallback" if interval is not None else None


def summarize(
    dates: Sequence[date],
    rows_by_date: Mapping[date, Mapping[str, Observation]],
    facts: Mapping[date, Mapping[str, DailyFact]],
    states_by_baseline: Mapping[int, Mapping[date, Mapping[str, StatePoint]]],
    events: Sequence[SignalEvent],
    phase_bounds: Mapping[str, tuple[date, date]],
    phase_by_date: Mapping[date, str],
    input_hash: str,
    *,
    source_trading_days: int,
    source_observations: int,
    excluded_dates: Mapping[date, int],
) -> dict[str, object]:
    baseline_rates = _baseline_outcomes(dates, facts, phase_by_date)
    metrics: dict[str, object] = {}
    for baseline in BASELINES:
        baseline_result: dict[str, object] = {}
        for phase in ("research", "calibration", "holdout", "all"):
            selected = [
                event
                for event in events
                if event.baseline == baseline and (phase == "all" or event.phase == phase)
            ]
            phase_result: dict[str, object] = {
                "event_count": len(selected),
                "entry_count": sum(event.entry_type == "entry" for event in selected),
                "retention_count": sum(event.entry_type == "retention" for event in selected),
            }
            for horizon in (1, 3, 5):
                field = f"success_{horizon}d"
                rate = sum(bool(getattr(event, field)) for event in selected) / len(selected) if selected else None
                phase_result[f"success_{horizon}d_rate"] = rate
                interval, interval_method = _confidence_interval(selected, field)
                phase_result[f"success_{horizon}d_ci95"] = list(interval) if interval else None
                phase_result[f"success_{horizon}d_ci95_method"] = interval_method
                if phase != "all" and rate is not None:
                    natural_rate = baseline_rates.get(phase, {}).get(f"success_{horizon}d_rate")
                    phase_result[f"success_{horizon}d_lift"] = (
                        rate / float(natural_rate) if natural_rate not in (None, 0) else None
                    )
            phase_result["by_entry_type"] = {}
            for entry_type in ("entry", "retention"):
                subgroup = [event for event in selected if event.entry_type == entry_type]
                phase_result["by_entry_type"][entry_type] = {
                    "event_count": len(subgroup),
                    **{
                        f"success_{horizon}d_rate": (
                            sum(bool(getattr(event, f"success_{horizon}d")) for event in subgroup)
                            / len(subgroup)
                            if subgroup
                            else None
                        )
                        for horizon in (1, 3, 5)
                    },
                }
            baseline_result[phase] = phase_result
        metrics[str(baseline)] = baseline_result

    sector_counts_by_date = {current_date: len(rows) for current_date, rows in rows_by_date.items()}
    state_counts = {
        str(baseline): sum(len(rows) for rows in states_by_baseline[baseline].values())
        for baseline in BASELINES
    }
    return {
        "experiment_id": EXPERIMENT_ID,
        "input": {
            "sha256": input_hash,
            "start_date": dates[0].isoformat(),
            "end_date": dates[-1].isoformat(),
            "source_trading_days": source_trading_days,
            "valid_published_days": len(dates),
            "source_observations": source_observations,
            "valid_observations": sum(sector_counts_by_date.values()),
            "sector_count_min": min(sector_counts_by_date.values()),
            "sector_count_max": max(sector_counts_by_date.values()),
            "excluded_incomplete_dates": {
                current_date.isoformat(): count
                for current_date, count in sorted(excluded_dates.items())
            },
        },
        "config": {
            "baselines": list(BASELINES),
            "amount_window": AMOUNT_WINDOW,
            "trend_window": TREND_WINDOW,
            "lambda": LAMBDA,
            "z_clip": Z_CLIP,
            "signal_level": SIGNAL_LEVEL,
            "reset_level": RESET_LEVEL,
            "up_share_min": UP_SHARE_MIN,
            "top_list_percentile": TOP_LIST_PERCENTILE,
            "bootstrap_block_days": BOOTSTRAP_BLOCK_DAYS,
            "bootstrap_samples": BOOTSTRAP_SAMPLES,
            "bootstrap_confidence": BOOTSTRAP_CONFIDENCE,
            "random_seed": RANDOM_SEED,
        },
        "phase_bounds": {
            phase: {"start": bounds[0].isoformat(), "end": bounds[1].isoformat()}
            for phase, bounds in phase_bounds.items()
        },
        "state_rows": state_counts,
        "natural_baseline": baseline_rates,
        "metrics": metrics,
    }


def write_outputs(output_dir: Path, events: Sequence[SignalEvent], summary: Mapping[str, object]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    events_path = output_dir / "signal-events.csv"
    event_fields = list(asdict(events[0]).keys()) if events else [field.name for field in SignalEvent.__dataclass_fields__.values()]
    with events_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=event_fields)
        writer.writeheader()
        for event in events:
            row = asdict(event)
            row["trade_date"] = event.trade_date.isoformat()
            writer.writerow(row)

    report_lines = [
        "# 板块雷达东财一级行业 60/120 日回测首轮结果",
        "",
        f"- 实验：`{summary['experiment_id']}`",
        f"- 输入：{summary['input']['start_date']}..{summary['input']['end_date']}，{summary['input']['valid_published_days']} 个完整发布交易日",
        f"- 行业数：每日 {summary['input']['sector_count_min']}..{summary['input']['sector_count_max']}",
        f"- 排除不完整日期：{len(summary['input']['excluded_incomplete_dates'])} 日",
        "- 数据源：Prod `trade_calendar + wealth_sector_hierarchy + dc_daily`，全程只读",
        "- 本轮不使用宽基指数，不计算 250 日基线",
        "",
        "## 核心结果",
        "",
        "| 基线 | 阶段 | 事件数 | 次日成功率 | 3日成功率 | 5日成功率 |",
        "|---:|---|---:|---:|---:|---:|",
    ]
    metrics = summary["metrics"]
    for baseline in BASELINES:
        for phase in ("research", "calibration", "holdout", "all"):
            result = metrics[str(baseline)][phase]
            def format_rate(value: float | None) -> str:
                return "--" if value is None else f"{value:.1%}"
            report_lines.append(
                f"| {baseline} | {phase} | {result['event_count']} | "
                f"{format_rate(result['success_1d_rate'])} | "
                f"{format_rate(result['success_3d_rate'])} | "
                f"{format_rate(result['success_5d_rate'])} |"
            )
    report_lines.extend(
        [
            "",
            "## 解释边界",
            "",
            "1. 本轮使用当前 31 个一级行业代码池，不宣称重建了历史层级版本。",
            "2. 结果是参数候选回测，不是投资建议，也不直接构成生产模型选择。",
            "3. 缺失事实不补零、不前向填充；无效窗口不产生状态或信号。",
            "4. 是否选择 60 或 120 日，必须同时看样本外 Lift、事件数量、覆盖和置信区间。",
            "",
        ]
    )
    (output_dir / "report.md").write_text("\n".join(report_lines), encoding="utf-8")


def run(input_csv: Path, output_dir: Path, *, expected_sector_count: int = 31) -> dict[str, object]:
    source_dates, source_rows_by_date, input_hash = load_observations(input_csv)
    sector_counts = [len(rows) for rows in source_rows_by_date.values()]
    if max(sector_counts) != expected_sector_count:
        raise ValueError(
            f"expected a {expected_sector_count}-sector cohort, observed daily maximum {max(sector_counts)}"
        )
    excluded_dates = {
        current_date: len(rows)
        for current_date, rows in source_rows_by_date.items()
        if len(rows) != expected_sector_count
    }
    dates = [current_date for current_date in source_dates if current_date not in excluded_dates]
    rows_by_date = {current_date: source_rows_by_date[current_date] for current_date in dates}
    if len(dates) < AMOUNT_WINDOW + max(BASELINES) + 5:
        raise ValueError("not enough complete published days for the 120-day experiment")
    facts = build_daily_facts(dates, rows_by_date)
    states_by_baseline = {
        baseline: build_states(dates, facts, baseline)
        for baseline in BASELINES
    }
    evaluation_dates = common_evaluation_dates(dates, states_by_baseline)
    phase_by_date, phase_bounds = split_phases(evaluation_dates)
    events = build_signal_events(
        dates,
        rows_by_date,
        facts,
        states_by_baseline,
        phase_by_date,
    )
    summary = summarize(
        dates,
        rows_by_date,
        facts,
        states_by_baseline,
        events,
        phase_bounds,
        phase_by_date,
        input_hash,
        source_trading_days=len(source_dates),
        source_observations=sum(len(rows) for rows in source_rows_by_date.values()),
        excluded_dates=excluded_dates,
    )
    write_outputs(output_dir, events, summary)
    return summary


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the fixed Eastmoney L1 sector-radar backtest")
    parser.add_argument("--input-csv", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(list(argv) if argv is not None else None)
    summary = run(args.input_csv, args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
