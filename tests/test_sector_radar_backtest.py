from __future__ import annotations

import csv
import math
from datetime import date, timedelta
from pathlib import Path

import pytest

from scripts.research.sector_radar_backtest import (
    BASELINES,
    Observation,
    build_daily_facts,
    build_states,
    is_turn_hot_signal,
    robust_z,
    run,
)
from scripts.research.sector_radar_signal_grid import SIGNAL_LEVELS, build_grid_summary


def _synthetic_rows(day_count: int = 190, sector_count: int = 31):
    start = date(2025, 1, 1)
    dates = [start + timedelta(days=index) for index in range(day_count)]
    rows = {}
    for day_index, current_date in enumerate(dates):
        daily = {}
        for sector_index in range(sector_count):
            code = f"BK{sector_index:04d}.DC"
            daily[code] = Observation(
                trade_date=current_date,
                sector_code=code,
                sector_name=f"行业{sector_index}",
                pct_change=(
                    math.sin(day_index / 7.0 + sector_index / 5.0) * 2.0
                    + sector_index * 0.01
                ),
                amount=(
                    1_000_000.0
                    + sector_index * 10_000.0
                    + day_index * 1_000.0
                    + math.cos(day_index / 6.0 + sector_index) * 50_000.0
                ),
            )
        rows[current_date] = daily
    return dates, rows


def _write_csv(path: Path, dates, rows) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["trade_date", "sector_code", "sector_name", "pct_change", "amount"],
        )
        writer.writeheader()
        for current_date in dates:
            for row in rows[current_date].values():
                writer.writerow(
                    {
                        "trade_date": current_date.isoformat(),
                        "sector_code": row.sector_code,
                        "sector_name": row.sector_name,
                        "pct_change": row.pct_change,
                        "amount": row.amount,
                    }
                )


def test_only_60_and_120_are_registered() -> None:
    assert BASELINES == (60, 120)
    assert 250 not in BASELINES


def test_robust_z_is_clipped_and_rejects_zero_mad() -> None:
    assert robust_z(99.0, [1.0, 2.0, 3.0, 4.0, 5.0]) == 3.0
    assert robust_z(2.0, [1.0, 1.0, 1.0]) is None


def test_signal_requires_crossing_trend_and_armed_state() -> None:
    states = [55.0, 57.0, 59.0, 61.0, 63.0, 65.0, 67.0, 68.0, 69.0, 71.0]
    assert is_turn_hot_signal(states, armed=True)
    assert not is_turn_hot_signal(states, armed=False)
    assert not is_turn_hot_signal([71.0] * 10, armed=True)
    lower_states = [45.0, 47.0, 49.0, 51.0, 53.0, 55.0, 57.0, 58.0, 59.0, 61.0]
    assert is_turn_hot_signal(lower_states, armed=True, signal_level=60.0)
    assert not is_turn_hot_signal(lower_states, armed=True, signal_level=65.0)


def test_future_row_change_does_not_modify_prior_state() -> None:
    dates, rows = _synthetic_rows(day_count=170, sector_count=3)
    facts_before = build_daily_facts(dates, rows)
    states_before = build_states(dates, facts_before, 60)

    last_date = dates[-1]
    changed = {current_date: dict(daily) for current_date, daily in rows.items()}
    original = changed[last_date]["BK0000.DC"]
    changed[last_date]["BK0000.DC"] = Observation(
        trade_date=last_date,
        sector_code=original.sector_code,
        sector_name=original.sector_name,
        pct_change=99.0,
        amount=original.amount * 20,
    )
    facts_after = build_daily_facts(dates, changed)
    states_after = build_states(dates, facts_after, 60)

    prior_date = dates[-2]
    assert states_before[prior_date]["BK0000.DC"] == states_after[prior_date]["BK0000.DC"]


def test_missing_day_is_not_forward_filled() -> None:
    dates, rows = _synthetic_rows(day_count=100, sector_count=3)
    missing_date = dates[50]
    del rows[missing_date]["BK0000.DC"]
    facts = build_daily_facts(dates, rows)

    assert "BK0000.DC" not in facts[missing_date]
    assert facts[dates[51]]["BK0000.DC"].amount_ratio_20 is None


def test_run_writes_fixed_experiment_outputs(tmp_path: Path) -> None:
    dates, rows = _synthetic_rows()
    input_path = tmp_path / "input.csv"
    output_dir = tmp_path / "output"
    _write_csv(input_path, dates, rows)

    summary = run(input_path, output_dir)

    assert summary["config"]["baselines"] == [60, 120]
    assert summary["input"]["sector_count_min"] == 31
    assert summary["phase_bounds"]["holdout"]["end"] < dates[-1].isoformat()
    assert (output_dir / "summary.json").is_file()
    assert (output_dir / "signal-events.csv").is_file()
    assert (output_dir / "report.md").is_file()


def test_run_excludes_incomplete_cross_section_without_filling(tmp_path: Path) -> None:
    dates, rows = _synthetic_rows()
    incomplete_date = dates[90]
    del rows[incomplete_date]["BK0000.DC"]
    input_path = tmp_path / "input.csv"
    _write_csv(input_path, dates, rows)

    summary = run(input_path, tmp_path / "output")

    assert summary["input"]["source_trading_days"] == 190
    assert summary["input"]["valid_published_days"] == 189
    assert summary["input"]["excluded_incomplete_dates"] == {
        incomplete_date.isoformat(): 30,
    }


def test_signal_grid_keeps_baselines_fixed_and_splits_event_types(tmp_path: Path) -> None:
    dates, rows = _synthetic_rows()
    input_path = tmp_path / "input.csv"
    _write_csv(input_path, dates, rows)

    summary = build_grid_summary(input_path)

    assert summary["config"]["baselines"] == [60, 120]
    assert summary["config"]["signal_levels"] == [55, 60, 65, 70]
    assert SIGNAL_LEVELS == (55.0, 60.0, 65.0, 70.0)
    assert 250 not in summary["config"]["baselines"]
    for baseline in ("60", "120"):
        for level in ("55", "60", "65", "70"):
            assert set(summary["grid"][baseline][level]["all"]) == {"early", "retention"}
            assert "entry_within_3d" in summary["grid"][baseline][level]["all"]["early"]["metrics"]
            assert "majority_3d" in summary["grid"][baseline][level]["all"]["retention"]["metrics"]
            assert "sector_event_counts" in summary["grid"][baseline][level]["all"]["early"]


def test_run_rejects_wrong_cohort_size(tmp_path: Path) -> None:
    dates, rows = _synthetic_rows(day_count=190, sector_count=30)
    input_path = tmp_path / "input.csv"
    _write_csv(input_path, dates, rows)

    with pytest.raises(ValueError, match="expected a 31-sector cohort"):
        run(input_path, tmp_path / "output")
