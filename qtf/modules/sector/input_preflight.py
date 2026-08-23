from __future__ import annotations

import itertools
import math
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from qtf.contracts.errors import QtfRequestInvalid
from qtf.contracts.parameters import ParameterValueSource
from qtf.contracts.runtime import (
    ExecutionPlan,
    InputPreflightIssueRecord,
    InputPreflightStatus,
    RemediationOwner,
)
from qtf.engine.canonical_hash import canonical_json_hash
from qtf.modules.sector.input_contract import SectorInputSnapshot
from qtf.modules.sector.parameter_schema import resolve_sector_heat_parameters
from qtf.modules.sector.plan_estimator import SECTOR_L2_ESTIMATOR_VERSION, estimate_plan_budget


HARD_GATES = (
    "INPUT",
    "TIME_FRONTIER",
    "FUTURE_LEAKAGE",
    "WARMUP",
    "COVERAGE",
    "OUT_OF_SAMPLE_SENSITIVITY",
)
STOP_CONDITIONS = (
    "INPUT_BLOCKED",
    "PLAN_BUDGET_EXCEEDED",
    "CANCEL_REQUESTED_AT_SAFE_POINT",
    "UNEXPECTED_EXECUTION_FAILURE",
)


@dataclass(frozen=True, slots=True)
class SectorPreflightEvaluation:
    status: InputPreflightStatus
    issues: tuple[InputPreflightIssueRecord, ...]
    group_members: dict[str, tuple[str, ...]]
    valid_group_days: tuple[tuple[date, str], ...]
    excluded_group_day_count: int
    valid_object_day_count: int
    plan: ExecutionPlan | None


def evaluate_sector_input(
    snapshot: SectorInputSnapshot,
    *,
    draft_effective_params: Mapping[str, object],
    success_definition: Mapping[str, object],
) -> SectorPreflightEvaluation:
    parameter_matrix = resolve_parameter_matrix(draft_effective_params)
    return evaluate_sector_input_with_matrix(
        snapshot,
        parameter_matrix=parameter_matrix,
        success_definition=success_definition,
    )


def evaluate_sector_input_with_matrix(
    snapshot: SectorInputSnapshot,
    *,
    parameter_matrix: tuple[dict[str, object], ...],
    success_definition: Mapping[str, object],
) -> SectorPreflightEvaluation:
    if not parameter_matrix:
        raise QtfRequestInvalid("frozen parameter matrix must not be empty")
    minimum_group_size = min(
        int(item["values"]["minimum_group_size"])  # type: ignore[index]
        for item in parameter_matrix
    )
    issues: list[InputPreflightIssueRecord] = []
    versions = {node.baseline_version for node in snapshot.hierarchy}
    if len(versions) != 1:
        issues.append(_issue("HIERARCHY_VERSION_INVALID", "core_serving.wealth_sector_hierarchy", "层级必须且只能有一个发布版本"))

    level_one = {node.sector_code: node for node in snapshot.hierarchy if node.industry_level == 1}
    level_two = tuple(node for node in snapshot.hierarchy if node.industry_level == 2)
    if not level_one or not level_two:
        issues.append(_issue("HIERARCHY_EMPTY", "core_serving.wealth_sector_hierarchy", "一级或二级行业对象池为空"))

    group_members: dict[str, list[str]] = defaultdict(list)
    for node in level_two:
        parent = node.parent_sector_code
        if parent is None or parent not in level_one or node.root_sector_code != parent:
            issues.append(
                _issue(
                    "HIERARCHY_PARENT_INVALID",
                    "core_serving.wealth_sector_hierarchy",
                    "二级行业父级或 root 闭包非法",
                    object_key=node.sector_code,
                )
            )
            continue
        group_members[parent].append(node.sector_code)

    normalized_groups = {key: tuple(sorted(value)) for key, value in sorted(group_members.items())}
    for parent, members in normalized_groups.items():
        if len(members) < minimum_group_size:
            issues.append(
                InputPreflightIssueRecord(
                    code="GROUP_BELOW_MINIMUM",
                    severity="WARN",
                    dataset_key="core_serving.wealth_sector_hierarchy",
                    object_key=parent,
                    message="直属二级行业数量低于冻结的最小比较组规模",
                    remediation_owner=RemediationOwner.PROD,
                    evidence={"member_count": len(members), "minimum_group_size": minimum_group_size},
                )
            )

    open_dates = set(snapshot.trade_dates)
    rows_by_group_day: dict[tuple[date, str], set[str]] = defaultdict(set)
    parent_by_sector = {
        sector: parent
        for parent, members in normalized_groups.items()
        for sector in members
    }
    seen_keys: set[tuple[date, str]] = set()
    for row in snapshot.observations:
        key = (row.trade_date, row.sector_code)
        if key in seen_keys:
            issues.append(_issue("DC_DAILY_DUPLICATE", "core_serving.dc_daily", "板块日行情业务键重复", trade_date=row.trade_date, object_key=row.sector_code))
        seen_keys.add(key)
        if row.trade_date not in open_dates:
            issues.append(_issue("DC_DAILY_NON_TRADING_DATE", "core_serving.dc_daily", "板块日行情日期不是 SSE 开放日", trade_date=row.trade_date, object_key=row.sector_code))
        if not math.isfinite(row.pct_change) or not math.isfinite(row.amount) or row.amount <= 0:
            issues.append(_issue("DC_DAILY_VALUE_INVALID", "core_serving.dc_daily", "涨跌幅或成交额为空、非有限或成交额非正", trade_date=row.trade_date, object_key=row.sector_code))
        parent = parent_by_sector.get(row.sector_code)
        if parent is not None:
            rows_by_group_day[(row.trade_date, parent)].add(row.sector_code)

    valid_group_days: list[tuple[date, str]] = []
    excluded_count = 0
    valid_object_day_count = 0
    for trade_date in snapshot.trade_dates:
        for parent, members in normalized_groups.items():
            if len(members) < minimum_group_size:
                excluded_count += 1
                continue
            actual = rows_by_group_day.get((trade_date, parent), set())
            missing = sorted(set(members) - actual)
            if missing:
                excluded_count += 1
                issues.append(
                    InputPreflightIssueRecord(
                        code="INCOMPLETE_GROUP_DAY",
                        severity="WARN",
                        dataset_key="core_serving.dc_daily",
                        trade_date=trade_date,
                        object_key=parent,
                        message="父级直属二级行业当日行情不完整，当前组日被排除",
                        remediation_owner=RemediationOwner.PROD,
                        evidence={"missing_sector_codes": missing},
                    )
                )
                continue
            valid_group_days.append((trade_date, parent))
            valid_object_day_count += len(members)

    if not valid_group_days:
        issues.append(_issue("NO_VALID_GROUP_DAY", "core_serving.dc_daily", "请求范围内没有可计算的完整父级组日"))

    blocked = any(issue.severity == "ERROR" for issue in issues)
    plan = None
    if not blocked:
        plan = build_execution_plan(
            snapshot=snapshot,
            parameter_matrix=parameter_matrix,
            success_definition=success_definition,
            group_day_count=len(valid_group_days) + excluded_count,
            valid_object_day_count=valid_object_day_count,
        )
    return SectorPreflightEvaluation(
        status=InputPreflightStatus.BLOCKED if blocked else InputPreflightStatus.PASS,
        issues=tuple(issues),
        group_members=normalized_groups,
        valid_group_days=tuple(valid_group_days),
        excluded_group_day_count=excluded_count,
        valid_object_day_count=valid_object_day_count,
        plan=plan,
    )


def resolve_parameter_matrix(draft_effective_params: Mapping[str, object]) -> tuple[dict[str, object], ...]:
    if set(draft_effective_params) != {"values", "sources"}:
        raise QtfRequestInvalid("draft parameter selections must contain exactly values and sources")
    raw_values = draft_effective_params["values"]
    raw_sources = draft_effective_params["sources"]
    if not isinstance(raw_values, Mapping) or not isinstance(raw_sources, Mapping):
        raise QtfRequestInvalid("draft parameter values and sources must be objects")
    candidate_keys = tuple(
        sorted(key for key, source in raw_sources.items() if source == ParameterValueSource.CANDIDATE.value)
    )
    if not candidate_keys or any(key not in {"baseline_days", "trend_days"} for key in candidate_keys):
        raise QtfRequestInvalid("candidate dimensions must be a non-empty subset of baseline_days and trend_days")
    candidate_values: list[tuple[object, ...]] = []
    for key in candidate_keys:
        value = raw_values.get(key)
        if not isinstance(value, (list, tuple)) or not value:
            raise QtfRequestInvalid(f"candidate parameter must contain explicit values: {key}")
        if len(value) != len(set(value)):
            raise QtfRequestInvalid(f"candidate parameter values must be unique: {key}")
        candidate_values.append(tuple(value))

    matrix: list[dict[str, object]] = []
    for combination in itertools.product(*candidate_values):
        scalar_values = dict(raw_values)
        for key, value in zip(candidate_keys, combination, strict=True):
            scalar_values[key] = value
        resolved = resolve_sector_heat_parameters(scalar_values, raw_sources)
        values = _jsonable(dict(resolved.effective.values))
        sources = {key: str(source.value) for key, source in resolved.effective.sources.items()}
        matrix.append(
            {
                "parameter_set_key": resolved.effective.parameter_hash,
                "values": values,
                "sources": sources,
                "parameter_hash": resolved.effective.parameter_hash,
            }
        )
    return tuple(sorted(matrix, key=lambda item: str(item["parameter_set_key"])))


def build_execution_plan(
    *,
    snapshot: SectorInputSnapshot,
    parameter_matrix: tuple[dict[str, object], ...],
    success_definition: Mapping[str, object],
    group_day_count: int,
    valid_object_day_count: int,
) -> ExecutionPlan:
    if set(success_definition) != {"selected_keys", "future_horizons"}:
        raise QtfRequestInvalid("success definition must contain selected_keys and future_horizons")
    if success_definition["selected_keys"] != ["FUTURE_SIBLING_RANK_CONTINUATION"]:
        raise QtfRequestInvalid("success definition is not registered for this template")
    if success_definition["future_horizons"] != [1, 3, 5]:
        raise QtfRequestInvalid("success definition future horizons must be [1, 3, 5]")
    first_values = parameter_matrix[0]["values"]
    if not isinstance(first_values, Mapping):
        raise AssertionError("resolved parameter values must be a mapping")
    candidate_fields = {"baseline_days", "trend_days"}
    fixed = {key: value for key, value in first_values.items() if key not in candidate_fields}
    estimator_inputs = {
        "source_rows": sum(item.row_count for item in snapshot.dataset_evidence),
        "group_days": group_day_count,
        "valid_object_days": valid_object_day_count,
        "parameter_combination_count": len(parameter_matrix),
    }
    budget = estimate_plan_budget(**estimator_inputs)
    payload: dict[str, object] = {
        "input_scope": {
            "source_content_hash": snapshot.content_hash,
            "effective_start_date": snapshot.trade_dates[0] if snapshot.trade_dates else None,
            "effective_end_date": snapshot.trade_dates[-1] if snapshot.trade_dates else None,
            "universe_count": len([node for node in snapshot.hierarchy if node.industry_level == 2]),
        },
        "estimator_inputs": estimator_inputs,
        "parameter_matrix": list(parameter_matrix),
        "fixed_parameters": fixed,
        "future_horizons": [1, 3, 5],
        "comparison_scope": "SIBLINGS",
        "sample_split": {
            "kind": "ORDERED_TRADING_DAYS",
            "in_sample_pct": 50,
            "calibration_pct": 25,
            "out_of_sample_pct": 25,
        },
        "primary_objective": "FUTURE_SIBLING_RANK_CONTINUATION",
        "success_definition": dict(success_definition),
        "hard_gates": list(HARD_GATES),
        "stop_conditions": list(STOP_CONDITIONS),
        "budget": budget,
        "estimator_version": SECTOR_L2_ESTIMATOR_VERSION,
    }
    plan_hash = canonical_json_hash(payload)
    return ExecutionPlan(
        input_scope=payload["input_scope"],  # type: ignore[arg-type]
        estimator_inputs=estimator_inputs,
        parameter_matrix=parameter_matrix,
        fixed_parameters=fixed,
        future_horizons=(1, 3, 5),
        comparison_scope="SIBLINGS",
        sample_split=payload["sample_split"],  # type: ignore[arg-type]
        primary_objective="FUTURE_SIBLING_RANK_CONTINUATION",
        success_definition=dict(success_definition),
        hard_gates=HARD_GATES,
        stop_conditions=STOP_CONDITIONS,
        budget=budget,
        estimator_version=SECTOR_L2_ESTIMATOR_VERSION,
        plan_hash=plan_hash,
    )


def execution_plan_hash(plan: ExecutionPlan) -> str:
    payload = plan.as_dict()
    payload.pop("plan_hash")
    return canonical_json_hash(payload)


def _issue(
    code: str,
    dataset_key: str,
    message: str,
    *,
    trade_date: date | None = None,
    object_key: str | None = None,
) -> InputPreflightIssueRecord:
    return InputPreflightIssueRecord(
        code=code,
        severity="ERROR",
        dataset_key=dataset_key,
        trade_date=trade_date,
        object_key=object_key,
        message=message,
        remediation_owner=RemediationOwner.PROD,
    )


def _jsonable(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    return value
