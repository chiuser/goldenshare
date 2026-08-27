from __future__ import annotations

import csv
import math
from datetime import date, timedelta
from pathlib import Path

from scripts.research.sector_radar_backtest import StatePoint
from scripts.research.sector_radar_robustness import (
    CANDIDATES,
    MatchedPair,
    OutcomeRecord,
    build_matched_controls,
    build_unsmoothed_states,
    run,
    summarize_leave_one_sector_out,
)


def _outcomes(value: bool) -> dict[str, bool]:
    return {
        "entry_within_1d": value,
        "entry_within_3d": value,
        "entry_within_5d": value,
        "majority_1d": value,
        "majority_3d": value,
        "majority_5d": value,
    }


def _record(current_date: date, sector_code: str, event_type: str, value: bool) -> OutcomeRecord:
    return OutcomeRecord(
        trade_date=current_date,
        sector_code=sector_code,
        sector_name=sector_code,
        event_type=event_type,
        outcomes=_outcomes(value),
    )


def _write_synthetic_csv(path: Path, day_count: int = 190, sector_count: int = 31) -> None:
    start = date(2025, 1, 1)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["trade_date", "sector_code", "sector_name", "pct_change", "amount"],
        )
        writer.writeheader()
        for day_index in range(day_count):
            current_date = start + timedelta(days=day_index)
            for sector_index in range(sector_count):
                writer.writerow(
                    {
                        "trade_date": current_date.isoformat(),
                        "sector_code": f"BK{sector_index:04d}.DC",
                        "sector_name": f"行业{sector_index}",
                        "pct_change": (
                            math.sin(day_index / 7.0 + sector_index / 5.0) * 2.0
                            + sector_index * 0.01
                        ),
                        "amount": (
                            1_000_000.0
                            + sector_index * 10_000.0
                            + day_index * 1_000.0
                            + math.cos(day_index / 6.0 + sector_index) * 50_000.0
                        ),
                    }
                )


def test_only_documented_robustness_candidates_are_registered() -> None:
    assert [candidate.candidate_id for candidate in CANDIDATES] == [
        "early_b60_t55",
        "early_b120_t55",
        "early_b60_t60",
        "early_b120_t60",
        "retention_b60_t70",
        "retention_b120_t70",
    ]
    assert {candidate.baseline for candidate in CANDIDATES} == {60, 120}
    assert all(candidate.signal_level != 65 for candidate in CANDIDATES)


def test_matched_controls_are_same_sector_type_non_signal_and_unique() -> None:
    dates = [date(2025, 1, day) for day in range(1, 7)]
    signals = [
        _record(dates[1], "BK0001.DC", "early", True),
        _record(dates[4], "BK0001.DC", "early", False),
    ]
    records = {
        (dates[0], "BK0001.DC"): _record(dates[0], "BK0001.DC", "early", False),
        (dates[1], "BK0001.DC"): signals[0],
        (dates[2], "BK0001.DC"): _record(dates[2], "BK0001.DC", "retention", True),
        (dates[3], "BK0001.DC"): _record(dates[3], "BK0001.DC", "early", True),
        (dates[4], "BK0001.DC"): signals[1],
        (dates[5], "BK0001.DC"): _record(dates[5], "BK0001.DC", "early", False),
        (dates[0], "BK0002.DC"): _record(dates[0], "BK0002.DC", "early", True),
    }
    environment = {current_date: (float(index), float(index)) for index, current_date in enumerate(dates)}

    pairs = build_matched_controls(signals, records, environment, dates)

    assert len(pairs) == 2
    assert len({(pair.control.trade_date, pair.control.sector_code) for pair in pairs}) == 2
    signal_dates = {record.trade_date for record in signals}
    assert all(pair.control.trade_date not in signal_dates for pair in pairs)
    assert all(pair.control.sector_code == pair.signal.sector_code for pair in pairs)
    assert all(pair.control.event_type == pair.signal.event_type for pair in pairs)


def test_unsmoothed_rule_uses_state_input_instead_of_smoothed_heat() -> None:
    dates = [date(2025, 1, 1) + timedelta(days=index) for index in range(10)]
    raw_values = [45.0, 47.0, 49.0, 50.0, 51.0, 52.0, 53.0, 54.0, 54.5, 55.5]
    source = {
        current_date: {
            "BK0001.DC": StatePoint(
                state_input=raw_value,
                heat_state=10.0,
                signal=False,
            )
        }
        for current_date, raw_value in zip(dates, raw_values)
    }

    result = build_unsmoothed_states(
        dates,
        source,
        signal_level=55.0,
        reset_level=45.0,
    )

    assert result[dates[-1]]["BK0001.DC"].signal is True
    assert result[dates[-1]]["BK0001.DC"].heat_state == 55.5


def test_leave_one_sector_out_runs_each_sector_without_creating_special_params() -> None:
    day = date(2025, 1, 1)
    pairs = [
        MatchedPair(
            signal=_record(day, sector, "early", True),
            control=_record(day + timedelta(days=1), sector, "early", False),
            year_distance=0,
            trading_day_distance=1,
            environment_distance=0.0,
        )
        for sector in ("BK0001.DC", "BK0002.DC", "BK0003.DC")
    ]

    summary = summarize_leave_one_sector_out(
        pairs,
        "early",
        ["BK0001.DC", "BK0002.DC", "BK0003.DC"],
    )

    assert summary["excluded_sector_count"] == 3
    assert all(item["pair_count"] == 2 for item in summary["by_excluded_sector"].values())
    assert "entry_within_3d" in summary["ranges"]


def test_run_emits_only_the_four_documented_robustness_sections(tmp_path: Path) -> None:
    input_path = tmp_path / "input.csv"
    output_dir = tmp_path / "output"
    _write_synthetic_csv(input_path)

    summary = run(input_path, output_dir)

    assert summary["evidence_status"] == "historical_robustness_only_not_new_holdout"
    assert summary["config"]["time_block"] == "calendar_quarter"
    assert summary["config"]["simple_rules"] == [
        "daily_relative_return_top20",
        "daily_amount_activity_top20",
        "unsmoothed_state_signal",
    ]
    for candidate in summary["candidates"].values():
        assert set(candidate) == {
            "config",
            "signal_event_count",
            "matched_controls",
            "quarterly_stability",
            "leave_one_sector_out",
            "simple_rule_counterexamples",
        }
    assert (output_dir / "summary.json").is_file()
    assert (output_dir / "matched-controls.csv").is_file()
