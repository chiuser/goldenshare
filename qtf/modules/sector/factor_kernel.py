from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from qtf.contracts.errors import QtfRequestInvalid
from qtf.engine.ranking import percentile_flags, percentile_ranks
from qtf.engine.robust_stats import (
    RobustZIssueCode,
    bounded_weighted_state,
    ewma,
    median,
    robust_z,
)
from qtf.engine.time_frontier import validate_trade_dates
from qtf.modules.sector.parameter_schema import (
    ComparisonScope,
    EventClusterRule,
    RankingRuleKind,
    SectorHeatParameters,
)
from qtf.modules.sector.signal_engine import evaluate_turn_hot


class SectorUniverse(StrEnum):
    EASTMONEY_INDUSTRY_L2 = "EASTMONEY_INDUSTRY_L2"


class SectorFactorIssueCode(StrEnum):
    INCOMPLETE_GROUP_DAY = "INCOMPLETE_GROUP_DAY"
    NON_FINITE_INPUT = "NON_FINITE_INPUT"
    NON_POSITIVE_AMOUNT = "NON_POSITIVE_AMOUNT"
    INSUFFICIENT_AMOUNT_HISTORY = "INSUFFICIENT_AMOUNT_HISTORY"
    INSUFFICIENT_BASELINE_HISTORY = "INSUFFICIENT_BASELINE_HISTORY"
    ZERO_MAD = "ZERO_MAD"
    INSUFFICIENT_TREND_HISTORY = "INSUFFICIENT_TREND_HISTORY"
    GROUP_BELOW_MINIMUM = "GROUP_BELOW_MINIMUM"


@dataclass(frozen=True, slots=True)
class SectorObservation:
    trade_date: date
    sector_code: str
    parent_sector_code: str
    pct_change: float
    amount: float


@dataclass(frozen=True, slots=True)
class SectorFactorIssue:
    trade_date: date
    parent_sector_code: str
    sector_code: str | None
    code: SectorFactorIssueCode
    field: str | None = None


@dataclass(frozen=True, slots=True)
class SectorHeatPoint:
    trade_date: date
    sector_code: str
    parent_sector_code: str
    relative_return_1d: float
    amount_ratio: float | None
    log_amount_ratio: float | None
    daily_horizontal_score: float | None
    daily_rank_pct: float | None
    on_list: bool | None
    relative_return_z: float | None
    log_amount_ratio_z: float | None
    state_input: float | None
    heat_state: float | None
    trend_slope: float | None
    upward_change_share: float | None
    signal: bool | None


@dataclass(frozen=True, slots=True)
class SectorHeatComputation:
    universe: SectorUniverse
    required_source_history_days: int
    points: tuple[SectorHeatPoint, ...]
    issues: tuple[SectorFactorIssue, ...]


def compute_sector_heat(
    *,
    universe: SectorUniverse | str,
    trade_dates: Sequence[date],
    group_members: Mapping[str, Sequence[str]],
    observations: Sequence[SectorObservation],
    parameters: SectorHeatParameters,
) -> SectorHeatComputation:
    normalized_universe = _validate_universe(universe)
    dates = validate_trade_dates(trade_dates)
    groups, parent_by_sector = _normalize_groups(group_members)
    _validate_parameter_scope(parameters)
    rows = _index_observations(dates, parent_by_sector, observations)

    amount_history: dict[str, list[float]] = defaultdict(list)
    factor_history: dict[str, list[tuple[float, float]]] = defaultdict(list)
    heat_history: dict[str, list[float]] = defaultdict(list)
    armed: dict[str, bool] = defaultdict(lambda: True)
    points: list[SectorHeatPoint] = []
    issues: list[SectorFactorIssue] = []

    for current_date in dates:
        rows_for_date = rows.get(current_date, {})
        for parent_code, expected_members in groups.items():
            group_rows = {
                code: rows_for_date[code]
                for code in expected_members
                if code in rows_for_date
            }
            missing_members = set(expected_members) - set(group_rows)
            if missing_members:
                issues.append(
                    SectorFactorIssue(
                        trade_date=current_date,
                        parent_sector_code=parent_code,
                        sector_code=None,
                        code=SectorFactorIssueCode.INCOMPLETE_GROUP_DAY,
                        field=",".join(sorted(missing_members)),
                    )
                )
                continue

            invalid_group = False
            for code, row in sorted(group_rows.items()):
                if not math.isfinite(row.pct_change) or not math.isfinite(row.amount):
                    issues.append(
                        SectorFactorIssue(
                            current_date,
                            parent_code,
                            code,
                            SectorFactorIssueCode.NON_FINITE_INPUT,
                        )
                    )
                    invalid_group = True
                elif row.amount <= 0:
                    issues.append(
                        SectorFactorIssue(
                            current_date,
                            parent_code,
                            code,
                            SectorFactorIssueCode.NON_POSITIVE_AMOUNT,
                            "amount",
                        )
                    )
                    invalid_group = True
            if invalid_group:
                continue

            return_center = median([row.pct_change for row in group_rows.values()])
            relative_returns = {
                code: row.pct_change - return_center
                for code, row in group_rows.items()
            }
            amount_ratios: dict[str, float | None] = {}
            log_amount_ratios: dict[str, float | None] = {}
            for code, row in sorted(group_rows.items()):
                history = amount_history[code]
                if len(history) < parameters.amount_lookback_days:
                    amount_ratios[code] = None
                    log_amount_ratios[code] = None
                    issues.append(
                        SectorFactorIssue(
                            current_date,
                            parent_code,
                            code,
                            SectorFactorIssueCode.INSUFFICIENT_AMOUNT_HISTORY,
                            "amount",
                        )
                    )
                else:
                    denominator = median(history[-parameters.amount_lookback_days :])
                    ratio = row.amount / denominator
                    amount_ratios[code] = ratio
                    log_amount_ratios[code] = math.log(ratio)
                history.append(row.amount)

            ranking_scores, ranking_percentiles, on_list = _daily_group_ranking(
                parent_code=parent_code,
                current_date=current_date,
                members=expected_members,
                relative_returns=relative_returns,
                log_amount_ratios=log_amount_ratios,
                parameters=parameters,
                issues=issues,
            )

            for code in expected_members:
                relative_return = relative_returns[code]
                amount_ratio = amount_ratios[code]
                log_amount_ratio = log_amount_ratios[code]
                relative_z: float | None = None
                amount_z: float | None = None
                state_input: float | None = None
                heat_state: float | None = None
                trend_slope: float | None = None
                upward_share: float | None = None
                signal: bool | None = None

                if log_amount_ratio is not None:
                    history = factor_history[code]
                    recent = history[-parameters.baseline_days :]
                    relative_result = robust_z(
                        relative_return,
                        [item[0] for item in recent],
                        required_count=parameters.baseline_days,
                        clip=parameters.z_clip,
                    )
                    amount_result = robust_z(
                        log_amount_ratio,
                        [item[1] for item in recent],
                        required_count=parameters.baseline_days,
                        clip=parameters.z_clip,
                    )
                    history.append((relative_return, log_amount_ratio))

                    if relative_result.valid and amount_result.valid:
                        relative_z = relative_result.value
                        amount_z = amount_result.value
                        if relative_z is None or amount_z is None:
                            raise AssertionError("valid robust Z result must contain a value")
                        state_input = bounded_weighted_state(
                            relative_z,
                            amount_z,
                            price_weight=parameters.price_weight,
                            amount_weight=parameters.amount_weight,
                            z_clip=parameters.z_clip,
                        )
                        previous_heat = heat_history[code][-1] if heat_history[code] else None
                        heat_state = ewma(
                            state_input,
                            previous_heat,
                            weight=parameters.ewma_lambda,
                        )
                        candidate_states = heat_history[code][-(parameters.trend_days - 1) :] + [heat_state]
                        if len(candidate_states) < parameters.trend_days:
                            issues.append(
                                SectorFactorIssue(
                                    current_date,
                                    parent_code,
                                    code,
                                    SectorFactorIssueCode.INSUFFICIENT_TREND_HISTORY,
                                    "heat_state",
                                )
                            )
                        else:
                            evaluation = evaluate_turn_hot(
                                candidate_states,
                                armed=armed[code],
                                signal_threshold=parameters.signal_threshold,
                                reset_threshold=parameters.reset_threshold,
                                up_move_share_min=parameters.up_move_share_min,
                            )
                            signal = evaluation.signal
                            trend_slope = evaluation.slope
                            upward_share = evaluation.upward_share
                            armed[code] = evaluation.armed_after
                        heat_history[code].append(heat_state)
                    else:
                        _record_robust_issue(
                            issues,
                            current_date,
                            parent_code,
                            code,
                            "relative_return_1d",
                            relative_result.issue_code,
                        )
                        _record_robust_issue(
                            issues,
                            current_date,
                            parent_code,
                            code,
                            "log_amount_ratio",
                            amount_result.issue_code,
                        )
                        heat_history[code].clear()
                        armed[code] = True

                points.append(
                    SectorHeatPoint(
                        trade_date=current_date,
                        sector_code=code,
                        parent_sector_code=parent_code,
                        relative_return_1d=relative_return,
                        amount_ratio=amount_ratio,
                        log_amount_ratio=log_amount_ratio,
                        daily_horizontal_score=ranking_scores.get(code),
                        daily_rank_pct=ranking_percentiles.get(code),
                        on_list=on_list.get(code),
                        relative_return_z=relative_z,
                        log_amount_ratio_z=amount_z,
                        state_input=state_input,
                        heat_state=heat_state,
                        trend_slope=trend_slope,
                        upward_change_share=upward_share,
                        signal=signal,
                    )
                )

    return SectorHeatComputation(
        universe=normalized_universe,
        required_source_history_days=parameters.required_source_history_days,
        points=tuple(points),
        issues=tuple(issues),
    )


def _validate_universe(universe: SectorUniverse | str) -> SectorUniverse:
    try:
        normalized = SectorUniverse(universe)
    except (TypeError, ValueError) as exc:
        raise QtfRequestInvalid("M2 only supports Eastmoney level-2 industries") from exc
    if normalized is not SectorUniverse.EASTMONEY_INDUSTRY_L2:
        raise QtfRequestInvalid("M2 only supports Eastmoney level-2 industries")
    return normalized


def _validate_parameter_scope(parameters: SectorHeatParameters) -> None:
    if parameters.comparison_scope is not ComparisonScope.SIBLINGS:
        raise QtfRequestInvalid("M2 only supports sibling comparison")
    if parameters.event_cluster_rule is not EventClusterRule.RESET_ONLY:
        raise QtfRequestInvalid("M2 only supports reset-only signal clustering")
    if parameters.ranking_rule.kind is not RankingRuleKind.PERCENTILE_GTE:
        raise QtfRequestInvalid("M2 only supports percentile threshold ranking")


def _normalize_groups(
    group_members: Mapping[str, Sequence[str]],
) -> tuple[dict[str, tuple[str, ...]], dict[str, str]]:
    if not group_members:
        raise QtfRequestInvalid("group_members must not be empty")
    groups: dict[str, tuple[str, ...]] = {}
    parent_by_sector: dict[str, str] = {}
    for parent_code, members in sorted(group_members.items()):
        if not parent_code.strip():
            raise QtfRequestInvalid("parent sector code must not be blank")
        normalized_members = tuple(sorted(member.strip() for member in members))
        if not normalized_members or any(not member for member in normalized_members):
            raise QtfRequestInvalid(f"group members must not be empty: {parent_code}")
        if len(normalized_members) != len(set(normalized_members)):
            raise QtfRequestInvalid(f"duplicate group member: {parent_code}")
        for member in normalized_members:
            if member in parent_by_sector:
                raise QtfRequestInvalid(f"sector belongs to more than one parent: {member}")
            parent_by_sector[member] = parent_code
        groups[parent_code] = normalized_members
    return groups, parent_by_sector


def _index_observations(
    trade_dates: Sequence[date],
    parent_by_sector: Mapping[str, str],
    observations: Sequence[SectorObservation],
) -> dict[date, dict[str, SectorObservation]]:
    allowed_dates = set(trade_dates)
    rows: dict[date, dict[str, SectorObservation]] = defaultdict(dict)
    for row in observations:
        if row.trade_date not in allowed_dates:
            raise QtfRequestInvalid(f"observation date is outside the trade calendar: {row.trade_date}")
        expected_parent = parent_by_sector.get(row.sector_code)
        if expected_parent is None:
            raise QtfRequestInvalid(f"observation sector is outside frozen groups: {row.sector_code}")
        if row.parent_sector_code != expected_parent:
            raise QtfRequestInvalid(f"observation parent does not match frozen groups: {row.sector_code}")
        if row.sector_code in rows[row.trade_date]:
            raise QtfRequestInvalid(f"duplicate observation: {row.trade_date}/{row.sector_code}")
        rows[row.trade_date][row.sector_code] = row
    return dict(rows)


def _daily_group_ranking(
    *,
    parent_code: str,
    current_date: date,
    members: Sequence[str],
    relative_returns: Mapping[str, float],
    log_amount_ratios: Mapping[str, float | None],
    parameters: SectorHeatParameters,
    issues: list[SectorFactorIssue],
) -> tuple[dict[str, float], dict[str, float], dict[str, bool]]:
    if any(log_amount_ratios[code] is None for code in members):
        return {}, {}, {}
    if len(members) < parameters.minimum_group_size:
        issues.append(
            SectorFactorIssue(
                current_date,
                parent_code,
                None,
                SectorFactorIssueCode.GROUP_BELOW_MINIMUM,
            )
        )
        return {}, {}, {}

    price_ranks = percentile_ranks({code: relative_returns[code] for code in members})
    amount_ranks = percentile_ranks(
        {code: float(log_amount_ratios[code]) for code in members if log_amount_ratios[code] is not None}
    )
    scores = {
        code: 0.5 * price_ranks[code] + 0.5 * amount_ranks[code]
        for code in members
    }
    ranks = percentile_ranks(scores)
    flags = percentile_flags(ranks, threshold=parameters.ranking_rule.threshold)
    return scores, ranks, flags


def _record_robust_issue(
    issues: list[SectorFactorIssue],
    current_date: date,
    parent_code: str,
    sector_code: str,
    field: str,
    issue_code: RobustZIssueCode | None,
) -> None:
    if issue_code is None:
        return
    mapped = (
        SectorFactorIssueCode.ZERO_MAD
        if issue_code is RobustZIssueCode.ZERO_MAD
        else SectorFactorIssueCode.INSUFFICIENT_BASELINE_HISTORY
    )
    issues.append(SectorFactorIssue(current_date, parent_code, sector_code, mapped, field))
