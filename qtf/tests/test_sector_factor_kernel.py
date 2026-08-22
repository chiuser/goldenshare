from __future__ import annotations

import math
from dataclasses import replace
from datetime import date, timedelta

import pytest

from qtf.contracts.errors import QtfRequestInvalid
from qtf.contracts.parameters import ParameterValueSource
from qtf.modules.sector.factor_kernel import (
    SectorFactorIssueCode,
    SectorObservation,
    SectorUniverse,
    compute_sector_heat,
)
from qtf.modules.sector.parameter_schema import resolve_sector_heat_parameters


GROUPS = {
    "L1-A": ("A1", "A2", "A3"),
    "L1-B": ("B1", "B2", "B3"),
}


def test_kernel_uses_parent_local_ranking_and_future_changes_do_not_rewrite_history() -> None:
    dates, rows = _synthetic_input(100)
    parameters = _parameters()
    before = compute_sector_heat(
        universe=SectorUniverse.EASTMONEY_INDUSTRY_L2,
        trade_dates=dates,
        group_members=GROUPS,
        observations=rows,
        parameters=parameters,
    )
    changed = [
        replace(row, pct_change=99.0, amount=row.amount * 50)
        if row.trade_date == dates[-1] and row.parent_sector_code == "L1-B"
        else row
        for row in rows
    ]
    after = compute_sector_heat(
        universe=SectorUniverse.EASTMONEY_INDUSTRY_L2,
        trade_dates=dates,
        group_members=GROUPS,
        observations=changed,
        parameters=parameters,
    )

    before_a = [point for point in before.points if point.parent_sector_code == "L1-A"]
    after_a = [point for point in after.points if point.parent_sector_code == "L1-A"]
    assert before_a == after_a
    assert [point for point in before.points if point.trade_date < dates[-1]] == [
        point for point in after.points if point.trade_date < dates[-1]
    ]


def test_missing_member_invalidates_only_that_parent_day_without_filling() -> None:
    dates, rows = _synthetic_input(100)
    missing_date = dates[50]
    rows = [
        row
        for row in rows
        if not (row.trade_date == missing_date and row.sector_code == "A1")
    ]
    result = compute_sector_heat(
        universe=SectorUniverse.EASTMONEY_INDUSTRY_L2,
        trade_dates=dates,
        group_members=GROUPS,
        observations=rows,
        parameters=_parameters(),
    )

    assert not any(
        point.trade_date == missing_date and point.parent_sector_code == "L1-A"
        for point in result.points
    )
    assert len(
        [
            point
            for point in result.points
            if point.trade_date == missing_date and point.parent_sector_code == "L1-B"
        ]
    ) == 3
    assert len(
        [
            point
            for point in result.points
            if point.trade_date == dates[51] and point.parent_sector_code == "L1-A"
        ]
    ) == 3
    assert any(
        issue.trade_date == missing_date
        and issue.parent_sector_code == "L1-A"
        and issue.code is SectorFactorIssueCode.INCOMPLETE_GROUP_DAY
        for issue in result.issues
    )


def test_warmup_is_independent_and_ranking_does_not_use_candidate_state_weights() -> None:
    dates, rows = _synthetic_input(150)
    params_60 = _parameters(baseline_days=60, price_weight=0.8, amount_weight=0.2)
    params_120 = _parameters(baseline_days=120, price_weight=0.2, amount_weight=0.8)
    result_60 = compute_sector_heat(
        universe=SectorUniverse.EASTMONEY_INDUSTRY_L2,
        trade_dates=dates,
        group_members=GROUPS,
        observations=rows,
        parameters=params_60,
    )
    result_120 = compute_sector_heat(
        universe=SectorUniverse.EASTMONEY_INDUSTRY_L2,
        trade_dates=dates,
        group_members=GROUPS,
        observations=rows,
        parameters=params_120,
    )

    day_80_60 = _point(result_60, dates[80], "A1")
    day_80_120 = _point(result_120, dates[80], "A1")
    assert day_80_60.heat_state is not None
    assert day_80_120.heat_state is None
    assert {
        (point.trade_date, point.sector_code): point.daily_rank_pct
        for point in result_60.points
    } == {
        (point.trade_date, point.sector_code): point.daily_rank_pct
        for point in result_120.points
    }


def test_small_groups_have_no_binary_rank_label() -> None:
    dates, rows = _synthetic_input(30, groups={"L1-A": ("A1", "A2")})
    result = compute_sector_heat(
        universe=SectorUniverse.EASTMONEY_INDUSTRY_L2,
        trade_dates=dates,
        group_members={"L1-A": ("A1", "A2")},
        observations=rows,
        parameters=_parameters(minimum_group_size=3),
    )

    mature_points = [point for point in result.points if point.trade_date == dates[-1]]
    assert mature_points
    assert all(point.daily_rank_pct is None and point.on_list is None for point in mature_points)
    assert any(issue.code is SectorFactorIssueCode.GROUP_BELOW_MINIMUM for issue in result.issues)


def test_zero_mad_is_reported_without_creating_a_heat_state() -> None:
    dates, rows = _synthetic_input(90)
    fixed_returns = {
        "A1": 1.0,
        "A2": 2.0,
        "A3": 3.0,
        "B1": 1.0,
        "B2": 2.0,
        "B3": 3.0,
    }
    rows = [replace(row, pct_change=fixed_returns[row.sector_code]) for row in rows]

    result = compute_sector_heat(
        universe=SectorUniverse.EASTMONEY_INDUSTRY_L2,
        trade_dates=dates,
        group_members=GROUPS,
        observations=rows,
        parameters=_parameters(),
    )

    point = _point(result, dates[80], "A1")
    assert point.heat_state is None
    assert any(
        issue.trade_date == dates[80]
        and issue.sector_code == "A1"
        and issue.field == "relative_return_1d"
        and issue.code is SectorFactorIssueCode.ZERO_MAD
        for issue in result.issues
    )


@pytest.mark.parametrize(
    ("replacement", "issue_code"),
    [
        ({"amount": 0.0}, SectorFactorIssueCode.NON_POSITIVE_AMOUNT),
        ({"pct_change": float("nan")}, SectorFactorIssueCode.NON_FINITE_INPUT),
    ],
)
def test_invalid_source_value_invalidates_only_its_parent_day(replacement, issue_code) -> None:
    dates, rows = _synthetic_input(30)
    invalid_date = dates[10]
    changed = [
        replace(row, **replacement)
        if row.trade_date == invalid_date and row.sector_code == "A1"
        else row
        for row in rows
    ]
    result = compute_sector_heat(
        universe=SectorUniverse.EASTMONEY_INDUSTRY_L2,
        trade_dates=dates,
        group_members=GROUPS,
        observations=changed,
        parameters=_parameters(),
    )

    assert not any(
        point.trade_date == invalid_date and point.parent_sector_code == "L1-A"
        for point in result.points
    )
    assert len(
        [point for point in result.points if point.trade_date == invalid_date and point.parent_sector_code == "L1-B"]
    ) == 3
    assert any(
        issue.trade_date == invalid_date
        and issue.parent_sector_code == "L1-A"
        and issue.code is issue_code
        for issue in result.issues
    )


def test_kernel_rejects_sw_global_scope_unknown_members_and_duplicates() -> None:
    dates, rows = _synthetic_input(30)
    with pytest.raises(QtfRequestInvalid, match="only supports Eastmoney"):
        compute_sector_heat(
            universe="SW2021_L2",
            trade_dates=dates,
            group_members=GROUPS,
            observations=rows,
            parameters=_parameters(),
        )
    with pytest.raises(QtfRequestInvalid, match="outside frozen groups"):
        compute_sector_heat(
            universe=SectorUniverse.EASTMONEY_INDUSTRY_L2,
            trade_dates=dates,
            group_members=GROUPS,
            observations=rows + [SectorObservation(dates[0], "X1", "GLOBAL", 1.0, 1.0)],
            parameters=_parameters(),
        )
    with pytest.raises(QtfRequestInvalid, match="duplicate observation"):
        compute_sector_heat(
            universe=SectorUniverse.EASTMONEY_INDUSTRY_L2,
            trade_dates=dates,
            group_members=GROUPS,
            observations=rows + [rows[0]],
            parameters=_parameters(),
        )


def _parameters(**updates):
    values = {
        "baseline_days": 60,
        "trend_days": 5,
        "amount_lookback_days": 20,
        "ewma_lambda": 0.30,
        "price_weight": 0.50,
        "amount_weight": 0.50,
        "z_clip": 3.0,
        "signal_threshold": 70.0,
        "reset_threshold": 60.0,
        "up_move_share_min": 0.60,
        "future_horizons": [1, 3, 5],
        "comparison_scope": "SIBLINGS",
        "minimum_group_size": 3,
        "ranking_rule": {"kind": "PERCENTILE_GTE", "threshold": 80.0},
        "event_cluster_rule": "RESET_ONLY",
    }
    values.update(updates)
    sources = {
        key: (
            ParameterValueSource.CANDIDATE
            if key in {"baseline_days", "trend_days"}
            else ParameterValueSource.FIXED
        )
        for key in values
    }
    return resolve_sector_heat_parameters(values, sources).parameters


def _synthetic_input(day_count: int, *, groups=GROUPS):
    dates = tuple(date(2025, 1, 1) + timedelta(days=index) for index in range(day_count))
    rows: list[SectorObservation] = []
    for day_index, current_date in enumerate(dates):
        for parent_index, (parent, members) in enumerate(sorted(groups.items())):
            for member_index, sector_code in enumerate(members):
                phase = day_index / (5.0 + member_index)
                pct_change = (
                    math.sin(phase)
                    + 0.2 * math.cos(day_index / (3.0 + member_index))
                    + member_index * 0.15
                    + parent_index * 0.05
                )
                amount = (
                    1_000.0
                    * (1.0 + day_index * 0.002)
                    * (1.0 + member_index * 0.08)
                    * (1.1 + 0.1 * math.sin((day_index + member_index) / 6.0))
                )
                rows.append(
                    SectorObservation(
                        trade_date=current_date,
                        sector_code=sector_code,
                        parent_sector_code=parent,
                        pct_change=pct_change,
                        amount=amount,
                    )
                )
    return dates, rows


def _point(result, trade_date: date, sector_code: str):
    return next(
        point
        for point in result.points
        if point.trade_date == trade_date and point.sector_code == sector_code
    )
