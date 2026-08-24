from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta

import pytest

from qtf.contracts.errors import QtfRequestInvalid
from qtf.contracts.runtime import ExecutionPlan
from qtf.contracts.validation import ValidationContractRegistry
from qtf.engine.validation_hash import (
    gate_result_hash,
    parameter_result_hash,
    run_validation_result_hash,
    signal_event_hash,
)
from qtf.modules.sector.input_preflight import execution_plan_hash
from qtf.modules.sector.validation_contract import (
    SECTOR_L2_VALIDATION_CONTRACT,
    SECTOR_VALIDATION_CONTRACT_REGISTRY,
    build_sector_validation_gate_config,
    validate_sector_validation_selection,
    validation_success_definition,
)


def test_registered_validation_contract_freezes_entry_retention_and_future_rules() -> None:
    definition = SECTOR_VALIDATION_CONTRACT_REGISTRY.get(
        "sector_l2_continuation_validation_v1",
        1,
    )
    success = validation_success_definition()

    assert definition is SECTOR_L2_VALIDATION_CONTRACT
    assert success["event_types"] == ["ENTRY", "RETENTION"]
    assert success["future_horizon_rules"] == [
        {"horizon_trade_days": 1, "required_on_list_days": 1},
        {"horizon_trade_days": 3, "required_on_list_days": 2},
        {"horizon_trade_days": 5, "required_on_list_days": 3},
    ]
    assert success["missing_future_policy"] == "UNEVALUABLE"


def test_validation_registry_rejects_duplicate_and_unknown_versions() -> None:
    with pytest.raises(ValueError, match="duplicate validation contract"):
        ValidationContractRegistry(
            (SECTOR_L2_VALIDATION_CONTRACT, SECTOR_L2_VALIDATION_CONTRACT)
        )
    with pytest.raises(QtfRequestInvalid, match="not registered"):
        SECTOR_VALIDATION_CONTRACT_REGISTRY.get(
            "sector_l2_continuation_validation_v1",
            2,
        )


def test_validation_gate_config_is_complete_versioned_and_has_no_hidden_defaults() -> None:
    source_dates = _source_dates(required_history=149, warmup_probe=10)
    config = build_sector_validation_gate_config(
        _selection(),
        requested_start_date=date(2026, 8, 3),
        requested_end_date=date(2026, 8, 6),
        source_trade_dates=source_dates,
        required_history_trade_days=149,
    )

    assert config["validation_contract_key"] == "sector_l2_continuation_validation_v1"
    assert config["validation_contract_version"] == 1
    calendar = config["evaluation_calendar"]
    assert isinstance(calendar, dict)
    assert calendar["required_history_trade_days"] == 149
    assert calendar["warmup_probe_trade_days"] == 10
    assert calendar["label_tail_trade_days"] == 5
    assert calendar["split_rule"] == "ORDERED_TRADING_DAYS_50_25_25"
    assert config["gates"]["TIME_FRONTIER"] == {"max_future_read_count": 0}  # type: ignore[index]

    with pytest.raises(QtfRequestInvalid, match="missing"):
        validate_sector_validation_selection({})


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update({"unknown": 1}),
        lambda value: value["confidence_method"].update({"confidence_level": float("nan")}),  # type: ignore[union-attr]
        lambda value: value["gates"]["TIME_FRONTIER"].update({"max_future_read_count": 1}),  # type: ignore[index,union-attr]
        lambda value: value["gates"]["OUT_OF_SAMPLE_SENSITIVITY"].update(  # type: ignore[index,union-attr]
            {"required_horizons": [1, 5]}
        ),
        lambda value: value["gates"]["COVERAGE"].update(  # type: ignore[index,union-attr]
            {"min_parent_coverage_rate": 1.1}
        ),
    ],
)
def test_validation_gate_config_rejects_unknown_nonfinite_and_contract_violations(
    mutate,
) -> None:  # type: ignore[no-untyped-def]
    selection = _selection()
    mutate(selection)
    with pytest.raises(QtfRequestInvalid):
        validate_sector_validation_selection(selection)


def test_validation_calendar_rejects_missing_history_tail_and_short_split() -> None:
    complete = _source_dates(required_history=149, warmup_probe=10)
    with pytest.raises(QtfRequestInvalid, match="history and warmup"):
        build_sector_validation_gate_config(
            _selection(),
            requested_start_date=date(2026, 8, 3),
            requested_end_date=date(2026, 8, 6),
            source_trade_dates=complete[1:],
            required_history_trade_days=149,
        )
    with pytest.raises(QtfRequestInvalid, match="five-day label tail"):
        build_sector_validation_gate_config(
            _selection(),
            requested_start_date=date(2026, 8, 3),
            requested_end_date=date(2026, 8, 6),
            source_trade_dates=complete[:-1],
            required_history_trade_days=149,
        )
    short = tuple(
        date(2026, 8, 3) + timedelta(days=offset)
        for offset in range(-159, 2 + 5)
    )
    with pytest.raises(QtfRequestInvalid, match="50/25/25"):
        build_sector_validation_gate_config(
            _selection(),
            requested_start_date=date(2026, 8, 3),
            requested_end_date=date(2026, 8, 4),
            source_trade_dates=short,
            required_history_trade_days=149,
        )


def test_gate_config_changes_plan_hash_and_old_hash_is_not_current() -> None:
    plan = _plan()
    original_hash = execution_plan_hash(plan)
    changed_config = deepcopy(plan.validation_gate_config)
    changed_config["gates"]["COVERAGE"]["min_signal_event_count"] = 2  # type: ignore[index]
    changed_plan = replace(plan, validation_gate_config=changed_config)

    assert execution_plan_hash(changed_plan) != original_hash
    assert execution_plan_hash(changed_plan) != plan.plan_hash


def test_validation_evidence_hashes_are_stable_and_order_independent() -> None:
    gate = {"gate_key": "INPUT", "status": "PASS", "evidence": {"b": 2, "a": 1}}
    parameter = {"parameter_set_key": "p1", "effect_status": "SUPPORTED"}
    event = {
        "parameter_set_key": "p1",
        "signal_trade_date": "2026-08-03",
        "sector_code": "BK0001",
        "entry_type": "ENTRY",
    }
    assert gate_result_hash(gate) == gate_result_hash(deepcopy(gate))
    assert parameter_result_hash(parameter) == parameter_result_hash(deepcopy(parameter))
    assert signal_event_hash(event) == signal_event_hash(deepcopy(event))

    first = run_validation_result_hash(
        runtime_fingerprint={"commit": "a" * 40},
        gate_results=[gate, {"gate_key": "WARMUP", "status": "PASS"}],
        parameter_results=[parameter, {"parameter_set_key": "p2"}],
        signal_events=[event, {**event, "sector_code": "BK0002"}],
    )
    second = run_validation_result_hash(
        runtime_fingerprint={"commit": "a" * 40},
        gate_results=[{"gate_key": "WARMUP", "status": "PASS"}, gate],
        parameter_results=[{"parameter_set_key": "p2"}, parameter],
        signal_events=[{**event, "sector_code": "BK0002"}, event],
    )
    assert first == second
    with pytest.raises(QtfRequestInvalid, match="duplicate gate result"):
        run_validation_result_hash(
            runtime_fingerprint={},
            gate_results=[gate, gate],
            parameter_results=[],
            signal_events=[],
        )


def _source_dates(*, required_history: int, warmup_probe: int) -> tuple[date, ...]:
    evaluation_start = date(2026, 8, 3)
    evaluation_end = date(2026, 8, 6)
    first = evaluation_start - timedelta(days=required_history + warmup_probe)
    last = evaluation_end + timedelta(days=5)
    return tuple(
        first + timedelta(days=offset)
        for offset in range((last - first).days + 1)
    )


def _selection() -> dict[str, object]:
    return {
        "validation_contract_key": "sector_l2_continuation_validation_v1",
        "validation_contract_version": 1,
        "warmup_probe_trade_days": 10,
        "confidence_method": {
            "kind": "MOVING_BLOCK_BOOTSTRAP",
            "block_trade_days": 5,
            "resample_count": 200,
            "confidence_level": 0.95,
            "random_seed": 7,
        },
        "gates": {
            "INPUT": {
                "require_pass_preflight": True,
                "require_source_hash_match": True,
            },
            "TIME_FRONTIER": {"max_future_read_count": 0},
            "FUTURE_LEAKAGE": {"max_changed_pre_frontier_point_count": 0},
            "WARMUP": {
                "comparison_trade_days": 5,
                "max_heat_state_absolute_delta": 0.01,
                "max_signal_mismatch_rate": 0.0,
            },
            "COVERAGE": {
                "min_evaluable_trade_days": 1,
                "min_signal_event_count": 1,
                "min_entry_event_count": 0,
                "min_retention_event_count": 0,
                "min_parent_coverage_rate": 0.5,
                "max_single_parent_event_share": 1.0,
            },
            "OUT_OF_SAMPLE_SENSITIVITY": {
                "required_horizons": [1, 3, 5],
                "min_oos_lift_lower_bound_by_horizon": {"1": 0.0, "3": 0.0, "5": 0.0},
                "max_calibration_to_oos_success_rate_drop_by_horizon": {
                    "1": 0.2,
                    "3": 0.2,
                    "5": 0.2,
                },
                "min_neighbor_pass_rate": 0.5,
            },
        },
    }


def _plan() -> ExecutionPlan:
    config = build_sector_validation_gate_config(
        _selection(),
        requested_start_date=date(2026, 8, 3),
        requested_end_date=date(2026, 8, 6),
        source_trade_dates=_source_dates(required_history=149, warmup_probe=10),
        required_history_trade_days=149,
    )
    calendar = config["evaluation_calendar"]
    confidence = config["confidence_method"]
    assert isinstance(calendar, dict) and isinstance(confidence, dict)
    plan = ExecutionPlan(
        input_scope={"source_content_hash": "a" * 64},
        estimator_inputs={"source_rows": 1},
        parameter_matrix=({"parameter_set_key": "p1"},),
        fixed_parameters={"amount_lookback_days": 20},
        future_horizons=(1, 3, 5),
        comparison_scope="SIBLINGS",
        validation_contract_key="sector_l2_continuation_validation_v1",
        validation_contract_version=1,
        evaluation_calendar=calendar,
        sample_split={
            "kind": "ORDERED_TRADING_DAYS_50_25_25",
            "in_sample_pct": 50,
            "calibration_pct": 25,
            "out_of_sample_pct": 25,
        },
        primary_objective="FUTURE_SIBLING_RANK_CONTINUATION",
        success_definition=validation_success_definition(),
        confidence_method=confidence,
        validation_gate_config=config,
        hard_gates=tuple(item.value for item in SECTOR_L2_VALIDATION_CONTRACT.hard_gates),
        stop_conditions=("INPUT_BLOCKED",),
        budget={"parameter_combination_count": 1},
        estimator_version="test",
        plan_hash="",
    )
    return replace(plan, plan_hash=execution_plan_hash(plan))
