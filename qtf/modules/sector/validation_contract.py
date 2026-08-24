from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date

from qtf.contracts.errors import QtfRequestInvalid
from qtf.contracts.validation import (
    FutureHorizonRule,
    HorizonEvaluationStatus,
    SignalEntryType,
    ValidationContractDefinition,
    ValidationContractRegistry,
    ValidationGateKey,
)


SECTOR_L2_VALIDATION_CONTRACT_KEY = "sector_l2_continuation_validation_v1"
SECTOR_L2_VALIDATION_CONTRACT_VERSION = 1
SECTOR_L2_SPLIT_RULE = "ORDERED_TRADING_DAYS_50_25_25"
SECTOR_L2_CONFIDENCE_METHOD = "MOVING_BLOCK_BOOTSTRAP"

SECTOR_L2_VALIDATION_CONTRACT = ValidationContractDefinition(
    contract_key=SECTOR_L2_VALIDATION_CONTRACT_KEY,
    contract_version=SECTOR_L2_VALIDATION_CONTRACT_VERSION,
    primary_objective="FUTURE_SIBLING_RANK_CONTINUATION",
    event_types=(SignalEntryType.ENTRY, SignalEntryType.RETENTION),
    future_horizon_rules=(
        FutureHorizonRule(horizon_trade_days=1, required_on_list_days=1),
        FutureHorizonRule(horizon_trade_days=3, required_on_list_days=2),
        FutureHorizonRule(horizon_trade_days=5, required_on_list_days=3),
    ),
    label_tail_trade_days=5,
    split_rule=SECTOR_L2_SPLIT_RULE,
    hard_gates=tuple(ValidationGateKey),
    ranking_source="OBJECTIVE_SIBLING_PRICE_AMOUNT_EQUAL_WEIGHT",
    missing_future_policy=HorizonEvaluationStatus.UNEVALUABLE,
)
SECTOR_VALIDATION_CONTRACT_REGISTRY = ValidationContractRegistry(
    (SECTOR_L2_VALIDATION_CONTRACT,)
)


def validate_sector_validation_selection(value: Mapping[str, object]) -> dict[str, object]:
    """Validate explicit PLAN selections without supplying executable defaults."""
    _require_exact_keys(
        value,
        {
            "validation_contract_key",
            "validation_contract_version",
            "warmup_probe_trade_days",
            "confidence_method",
            "gates",
        },
        "validationGateConfig",
    )
    contract_key = _string(value["validation_contract_key"], "validationContractKey")
    contract_version = _integer(
        value["validation_contract_version"],
        "validationContractVersion",
        minimum=1,
    )
    contract = SECTOR_VALIDATION_CONTRACT_REGISTRY.get(contract_key, contract_version)
    warmup_probe_trade_days = _integer(
        value["warmup_probe_trade_days"],
        "warmupProbeTradeDays",
        minimum=1,
    )
    confidence = _validate_confidence_method(
        _mapping(value["confidence_method"], "confidenceMethod")
    )
    gates = _validate_gates(_mapping(value["gates"], "gates"), contract=contract)
    return {
        "validation_contract_key": contract.contract_key,
        "validation_contract_version": contract.contract_version,
        "warmup_probe_trade_days": warmup_probe_trade_days,
        "confidence_method": confidence,
        "gates": gates,
    }


def build_sector_validation_gate_config(
    selection: Mapping[str, object],
    *,
    requested_start_date: date,
    requested_end_date: date,
    source_trade_dates: Sequence[date],
    required_history_trade_days: int,
) -> dict[str, object]:
    normalized = validate_sector_validation_selection(selection)
    contract = SECTOR_VALIDATION_CONTRACT_REGISTRY.get(
        str(normalized["validation_contract_key"]),
        int(normalized["validation_contract_version"]),
    )
    if requested_start_date > requested_end_date:
        raise QtfRequestInvalid("requested evaluation start date must not be after end date")
    if required_history_trade_days < 1:
        raise QtfRequestInvalid("required history trade days must be positive")
    ordered_dates = tuple(source_trade_dates)
    if not ordered_dates or ordered_dates != tuple(sorted(set(ordered_dates))):
        raise QtfRequestInvalid("source trade dates must be sorted and unique")
    evaluation_dates = tuple(
        item for item in ordered_dates if requested_start_date <= item <= requested_end_date
    )
    if (
        not evaluation_dates
        or evaluation_dates[0] != requested_start_date
        or evaluation_dates[-1] != requested_end_date
    ):
        raise QtfRequestInvalid("requested evaluation boundaries must be published SSE trading days")
    in_sample_count = math.floor(len(evaluation_dates) * 0.50)
    calibration_count = math.floor(len(evaluation_dates) * 0.25)
    out_of_sample_count = len(evaluation_dates) - in_sample_count - calibration_count
    if min(in_sample_count, calibration_count, out_of_sample_count) < 1:
        raise QtfRequestInvalid("evaluation calendar is too short for the ordered 50/25/25 split")

    prefix_dates = tuple(item for item in ordered_dates if item < requested_start_date)
    tail_dates = tuple(item for item in ordered_dates if item > requested_end_date)
    warmup_probe_trade_days = int(normalized["warmup_probe_trade_days"])
    required_prefix_count = required_history_trade_days + warmup_probe_trade_days
    if len(prefix_dates) != required_prefix_count:
        raise QtfRequestInvalid("source range does not contain the complete history and warmup probe")
    if len(tail_dates) != contract.label_tail_trade_days:
        raise QtfRequestInvalid("source range does not contain the complete five-day label tail")

    evaluation_calendar = {
        "requested_evaluation_start_date": requested_start_date,
        "requested_evaluation_end_date": requested_end_date,
        "resolved_source_start_date": ordered_dates[0],
        "resolved_source_end_date": ordered_dates[-1],
        "required_history_trade_days": required_history_trade_days,
        "warmup_probe_trade_days": warmup_probe_trade_days,
        "label_tail_trade_days": contract.label_tail_trade_days,
        "split_rule": contract.split_rule,
        "evaluation_trade_day_count": len(evaluation_dates),
        "in_sample_trade_day_count": in_sample_count,
        "calibration_trade_day_count": calibration_count,
        "out_of_sample_trade_day_count": out_of_sample_count,
    }
    return {
        "validation_contract_key": contract.contract_key,
        "validation_contract_version": contract.contract_version,
        "evaluation_calendar": evaluation_calendar,
        "confidence_method": normalized["confidence_method"],
        "gates": normalized["gates"],
    }


def validation_success_definition() -> dict[str, object]:
    return SECTOR_L2_VALIDATION_CONTRACT.success_definition()


def _validate_confidence_method(value: Mapping[str, object]) -> dict[str, object]:
    _require_exact_keys(
        value,
        {"kind", "block_trade_days", "resample_count", "confidence_level", "random_seed"},
        "confidenceMethod",
    )
    if value["kind"] != SECTOR_L2_CONFIDENCE_METHOD:
        raise QtfRequestInvalid("confidence method is not registered for this validation contract")
    return {
        "kind": SECTOR_L2_CONFIDENCE_METHOD,
        "block_trade_days": _integer(value["block_trade_days"], "blockTradeDays", minimum=1),
        "resample_count": _integer(value["resample_count"], "resampleCount", minimum=1),
        "confidence_level": _number(
            value["confidence_level"],
            "confidenceLevel",
            minimum=0.0,
            maximum=1.0,
            minimum_inclusive=False,
            maximum_inclusive=False,
        ),
        "random_seed": _integer(value["random_seed"], "randomSeed", minimum=0),
    }


def _validate_gates(
    value: Mapping[str, object],
    *,
    contract: ValidationContractDefinition,
) -> dict[str, object]:
    expected = {item.value for item in contract.hard_gates}
    _require_exact_keys(value, expected, "gates")

    input_gate = _mapping(value[ValidationGateKey.INPUT.value], "gates.INPUT")
    _require_exact_keys(
        input_gate,
        {"require_pass_preflight", "require_source_hash_match"},
        "gates.INPUT",
    )
    if input_gate["require_pass_preflight"] is not True or input_gate["require_source_hash_match"] is not True:
        raise QtfRequestInvalid("INPUT gate must require PASS preflight and source hash match")

    time_frontier = _mapping(value[ValidationGateKey.TIME_FRONTIER.value], "gates.TIME_FRONTIER")
    _require_exact_keys(time_frontier, {"max_future_read_count"}, "gates.TIME_FRONTIER")
    if _integer(time_frontier["max_future_read_count"], "maxFutureReadCount", minimum=0) != 0:
        raise QtfRequestInvalid("TIME_FRONTIER maxFutureReadCount must be zero")

    future_leakage = _mapping(
        value[ValidationGateKey.FUTURE_LEAKAGE.value],
        "gates.FUTURE_LEAKAGE",
    )
    _require_exact_keys(
        future_leakage,
        {"max_changed_pre_frontier_point_count"},
        "gates.FUTURE_LEAKAGE",
    )
    if _integer(
        future_leakage["max_changed_pre_frontier_point_count"],
        "maxChangedPreFrontierPointCount",
        minimum=0,
    ) != 0:
        raise QtfRequestInvalid(
            "FUTURE_LEAKAGE maxChangedPreFrontierPointCount must be zero"
        )

    warmup = _mapping(value[ValidationGateKey.WARMUP.value], "gates.WARMUP")
    _require_exact_keys(
        warmup,
        {"comparison_trade_days", "max_heat_state_absolute_delta", "max_signal_mismatch_rate"},
        "gates.WARMUP",
    )
    coverage = _mapping(value[ValidationGateKey.COVERAGE.value], "gates.COVERAGE")
    _require_exact_keys(
        coverage,
        {
            "min_evaluable_trade_days",
            "min_signal_event_count",
            "min_entry_event_count",
            "min_retention_event_count",
            "min_parent_coverage_rate",
            "max_single_parent_event_share",
        },
        "gates.COVERAGE",
    )
    sensitivity = _mapping(
        value[ValidationGateKey.OUT_OF_SAMPLE_SENSITIVITY.value],
        "gates.OUT_OF_SAMPLE_SENSITIVITY",
    )
    _require_exact_keys(
        sensitivity,
        {
            "required_horizons",
            "min_oos_lift_lower_bound_by_horizon",
            "max_calibration_to_oos_success_rate_drop_by_horizon",
            "min_neighbor_pass_rate",
        },
        "gates.OUT_OF_SAMPLE_SENSITIVITY",
    )
    horizons = _integer_sequence(sensitivity["required_horizons"], "requiredHorizons")
    registered_horizons = tuple(
        item.horizon_trade_days for item in contract.future_horizon_rules
    )
    if horizons != registered_horizons:
        raise QtfRequestInvalid("requiredHorizons must be exactly [1, 3, 5]")

    return {
        ValidationGateKey.INPUT.value: {
            "require_pass_preflight": True,
            "require_source_hash_match": True,
        },
        ValidationGateKey.TIME_FRONTIER.value: {"max_future_read_count": 0},
        ValidationGateKey.FUTURE_LEAKAGE.value: {
            "max_changed_pre_frontier_point_count": 0,
        },
        ValidationGateKey.WARMUP.value: {
            "comparison_trade_days": _integer(
                warmup["comparison_trade_days"],
                "comparisonTradeDays",
                minimum=1,
            ),
            "max_heat_state_absolute_delta": _number(
                warmup["max_heat_state_absolute_delta"],
                "maxHeatStateAbsoluteDelta",
                minimum=0.0,
            ),
            "max_signal_mismatch_rate": _number(
                warmup["max_signal_mismatch_rate"],
                "maxSignalMismatchRate",
                minimum=0.0,
                maximum=1.0,
            ),
        },
        ValidationGateKey.COVERAGE.value: {
            "min_evaluable_trade_days": _integer(
                coverage["min_evaluable_trade_days"],
                "minEvaluableTradeDays",
                minimum=0,
            ),
            "min_signal_event_count": _integer(
                coverage["min_signal_event_count"],
                "minSignalEventCount",
                minimum=0,
            ),
            "min_entry_event_count": _integer(
                coverage["min_entry_event_count"],
                "minEntryEventCount",
                minimum=0,
            ),
            "min_retention_event_count": _integer(
                coverage["min_retention_event_count"],
                "minRetentionEventCount",
                minimum=0,
            ),
            "min_parent_coverage_rate": _number(
                coverage["min_parent_coverage_rate"],
                "minParentCoverageRate",
                minimum=0.0,
                maximum=1.0,
            ),
            "max_single_parent_event_share": _number(
                coverage["max_single_parent_event_share"],
                "maxSingleParentEventShare",
                minimum=0.0,
                maximum=1.0,
            ),
        },
        ValidationGateKey.OUT_OF_SAMPLE_SENSITIVITY.value: {
            "required_horizons": list(horizons),
            "min_oos_lift_lower_bound_by_horizon": _horizon_number_map(
                sensitivity["min_oos_lift_lower_bound_by_horizon"],
                "minOosLiftLowerBoundByHorizon",
                horizons=horizons,
            ),
            "max_calibration_to_oos_success_rate_drop_by_horizon": _horizon_number_map(
                sensitivity["max_calibration_to_oos_success_rate_drop_by_horizon"],
                "maxCalibrationToOosSuccessRateDropByHorizon",
                horizons=horizons,
                minimum=0.0,
                maximum=1.0,
            ),
            "min_neighbor_pass_rate": _number(
                sensitivity["min_neighbor_pass_rate"],
                "minNeighborPassRate",
                minimum=0.0,
                maximum=1.0,
            ),
        },
    }


def _horizon_number_map(
    value: object,
    field_name: str,
    *,
    horizons: tuple[int, ...],
    minimum: float | None = None,
    maximum: float | None = None,
) -> dict[str, float]:
    mapping = _mapping(value, field_name)
    expected = {str(item) for item in horizons}
    _require_exact_keys(mapping, expected, field_name)
    return {
        str(horizon): _number(
            mapping[str(horizon)],
            f"{field_name}.{horizon}",
            minimum=minimum,
            maximum=maximum,
        )
        for horizon in horizons
    }


def _require_exact_keys(value: Mapping[str, object], expected: set[str], field_name: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise QtfRequestInvalid(
            f"{field_name} fields are invalid; missing={missing}, unknown={unknown}"
        )


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise QtfRequestInvalid(f"{field_name} must be an object")
    return value


def _string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise QtfRequestInvalid(f"{field_name} must be a non-empty string")
    return value


def _integer(value: object, field_name: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise QtfRequestInvalid(f"{field_name} must be an integer >= {minimum}")
    return value


def _integer_sequence(value: object, field_name: str) -> tuple[int, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise QtfRequestInvalid(f"{field_name} must be an integer sequence")
    items = tuple(value)
    if any(isinstance(item, bool) or not isinstance(item, int) for item in items):
        raise QtfRequestInvalid(f"{field_name} must contain only integers")
    if not items or items != tuple(sorted(set(items))):
        raise QtfRequestInvalid(f"{field_name} must be sorted, unique and non-empty")
    return items


def _number(
    value: object,
    field_name: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    minimum_inclusive: bool = True,
    maximum_inclusive: bool = True,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise QtfRequestInvalid(f"{field_name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise QtfRequestInvalid(f"{field_name} must be a finite number")
    if minimum is not None and (
        number < minimum or (number == minimum and not minimum_inclusive)
    ):
        operator = ">=" if minimum_inclusive else ">"
        raise QtfRequestInvalid(f"{field_name} must be {operator} {minimum}")
    if maximum is not None and (
        number > maximum or (number == maximum and not maximum_inclusive)
    ):
        operator = "<=" if maximum_inclusive else "<"
        raise QtfRequestInvalid(f"{field_name} must be {operator} {maximum}")
    return number
