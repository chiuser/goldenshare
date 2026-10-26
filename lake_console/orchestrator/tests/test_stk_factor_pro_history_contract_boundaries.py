"""Independent wire samples from LLD 5.4/16; no file, source or instance I/O.

The literal references describe record structure only. They do not claim that
the files exist, that a run succeeded, or that the future PG reader is tested.
"""

from copy import deepcopy
from dataclasses import replace
from datetime import date

import pytest

from orchestrator.defs.run_contracts import stk_factor_pro as models

T, P = date(2026, 10, 16), date(2026, 10, 15)
SHA = "a" * 64
SILVER_SHA = "b" * 64
WHEN = "2026-10-16T19:00:00.000000+08:00"


def identity_wire():
    return {
        "creator_run_id": "run-a",
        "source_run_id": None,
        "execution_day": "2026-10-16",
        "target_trade_date": "2026-10-16",
        "previous_trade_date": "2026-10-15",
        "purpose": "today",
        "scheduled_slot": 0,
        "submission_no": None,
        "business_attempt": None,
    }


def reference(path, run="run-a", digest=SHA):
    return {"creator_run_id": run, "relative_path": path, "file_sha256": digest}


def range_wire(t_present=True, p_present=True, reasons=(1,)):
    return {
        "ts_code": "000001.SZ",
        "t_present": t_present,
        "p_present": p_present,
        "t_value": 2.0 if t_present else None,
        "p_value": 1.0 if p_present else None,
        "start_date": None,
        "end_date": None,
        "plan_reasons": list(reasons),
        "origin_target_dates": ["2026-10-16"],
        "origin_record_refs": [],
        "earliest_basis_kind": None,
        "earliest_basis_date": None,
    }


def coverage_wire():
    return {
        "target_trade_date": "2026-10-16",
        "complete": True,
        "raw_check_passed": True,
        "raw_file_sha256": SHA,
        "lifecycle_file_sha256": "c" * 64,
        "suspend_file_sha256": "d" * 64,
        "identity_file_sha256": "e" * 64,
        "expected_count": 2,
        "actual_count": 2,
        "missing_count": 0,
        "missing_sample_codes": [],
        "reason": "literal: both expected stocks are present",
        "raw_materialization_storage_id": 11,
        "raw_check_storage_id": 12,
        "missing_codes_ref": None,
    }


def silver_wire():
    return {
        "target_trade_date": "2026-10-16",
        "ready": True,
        "silver_file_sha256": SILVER_SHA,
        "current_raw_file_sha256": SHA,
        "source_raw_file_sha256": SHA,
        "silver_materialization_storage_id": 13,
        "silver_check_execution_id": 14,
        "reason": "literal: Silver was generated from this Raw",
    }


def eligibility_wire():
    return {
        "record_version": 1,
        "identity": identity_wire(),
        "history_plan_digest": SHA,
        "history_ranges_digest": SHA,
        "raw_coverage": coverage_wire(),
        "target_silver": silver_wire(),
        "evaluated_at": WHEN,
    }


def publication_wire():
    # LLD 5.4.3: only original-T history, and both actual layers for each day.
    targets = [
        {
            "trade_date": "2026-10-15",
            "layer": layer,
            "skip_no_file": False,
            "file_sha256": SHA if layer == "raw" else SILVER_SHA,
            "file_rows": 2,
            "checkpoint_ref": reference(
                f"publication/history/2026-10-15/{layer}/complete.json"
            ),
            "unrefreshed_count": 0,
            "scope_rows": 1,
            "scope_content_sha256": SHA,
            "scope_content_version": 1,
        }
        for layer in ("raw", "silver")
    ]
    return {
        "record_version": 1,
        "identity": identity_wire(),
        "phase": "history",
        "contract": {
            "contract_name": "stk_factor_pro",
            "contract_version": "1",
            "contract_content_digest": SHA,
            "processing_version": "1",
        },
        "history_plan_digest": SHA,
        "history_ranges_digest": SHA,
        "scope_digest": SHA,
        "history_input_digest": SHA,
        "source_complete_ref": reference("source/history/source-complete.json"),
        "day_source_digest": None,
        "source_manifest_digest": SHA,
        "targets": targets,
        "verified_at": WHEN,
    }


def recorded_results_wire():
    return {
        "target_trade_date": "2026-10-16",
        "day_result_ref": {"run_id": "run-a", "storage_id": 21},
        "history_result_ref": {"run_id": "success-run", "storage_id": 22},
        "history_plan_ref": reference("history-plan.json"),
        "history_ranges_ref": reference("history-ranges.parquet"),
        "raw_coverage": coverage_wire(),
        "bootstrap_context": None,
        "pending_plan_refs": [reference("history-plan.json", run="failed-run")],
        "successful_publication_refs": [
            reference(
                "publication/history/publication-complete.json", run="success-run"
            )
        ],
        "unresolved_day_failure_run_id": None,
        "unresolved_history_failure_run_id": "failed-run",
    }


@pytest.mark.parametrize(
    ("t_present", "p_present", "reasons"),
    [(True, False, (3,)), (False, True, (4,)), (False, False, (5,))],
)
def test_missing_factors_are_retained_without_fabricating_zero_or_start(
    t_present, p_present, reasons
):
    wire = range_wire(t_present, p_present, reasons)
    record = models.parse_stk_factor_pro_record(models.HistoryRange, wire)
    assert record.t_present is t_present and record.p_present is p_present
    assert record.t_value == (2.0 if t_present else None)
    assert record.p_value == (1.0 if p_present else None)
    assert record.start_date is None and record.end_date is None
    assert record.plan_reasons == reasons
    assert models.stk_factor_pro_record_to_dict(record) == wire


def test_prior_unfinished_range_survives_missing_factor_and_equal_values():
    wire = range_wire(True, False, (2, 3))
    wire.update(
        start_date="2026-10-14",
        end_date="2026-10-16",
        earliest_basis_kind=1,
        earliest_basis_date="2026-10-14",
    )
    missing = models.parse_stk_factor_pro_record(models.HistoryRange, wire)
    assert missing.start_date == date(2026, 10, 14) and missing.p_value is None
    equal = replace(missing, p_present=True, p_value=2.0, plan_reasons=(2,))
    assert equal.t_value == equal.p_value and equal.plan_reasons == (2,)
    assert equal.start_date == missing.start_date and equal.end_date == T


def test_proved_no_prior_history_keeps_reason_six_without_invented_range():
    wire = range_wire(True, False, (6,))
    record = models.parse_stk_factor_pro_record(models.HistoryRange, wire)
    assert record.plan_reasons == (6,)
    assert record.p_value is None
    assert record.start_date is None and record.earliest_basis_kind is None
    assert models.stk_factor_pro_record_to_dict(record) == wire


@pytest.mark.parametrize(
    ("record_type", "factory"),
    [
        (models.HistoryEligibilityRecord, eligibility_wire),
        (models.PublicationCompleteRecord, publication_wire),
        (models.StkFactorProRecordedResults, recorded_results_wire),
    ],
)
def test_nested_codec_matches_independent_complete_wire(record_type, factory):
    wire = factory()
    record = models.parse_stk_factor_pro_record(record_type, wire)
    assert models.stk_factor_pro_record_to_dict(record) == wire
    if record_type is models.HistoryEligibilityRecord:
        assert (
            record.raw_coverage.complete is True and record.target_silver.ready is True
        )
    elif record_type is models.PublicationCompleteRecord:
        assert [(target.trade_date, target.layer) for target in record.targets] == [
            (P, "raw"),
            (P, "silver"),
        ]
    else:
        assert record.pending_plan_refs[0].creator_run_id == "failed-run"
        assert record.successful_publication_refs[0].creator_run_id == "success-run"


def test_waiting_eligibility_preserves_unknown_coverage_and_unchecked_silver():
    wire = eligibility_wire()
    wire["target_silver"] = None
    wire["raw_coverage"].update(
        complete=None, expected_count=None, actual_count=None, missing_count=None
    )
    record = models.parse_stk_factor_pro_record(models.HistoryEligibilityRecord, wire)
    assert record.raw_coverage.complete is None and record.target_silver is None
    assert models.stk_factor_pro_record_to_dict(record) == wire


def bootstrap_context_wire():
    # LLD 10.5.4: the reference is relative to an operation, not to a run.
    # The original authorization may survive after current coverage is complete.
    return {
        "operation_id": "approved-import",
        "approval_digest": SHA,
        "target_trade_date": "2026-10-16",
        "authorized_date_result_digest": SHA,
        "authorized_gap_input_digest": SHA,
        "authorized_missing_count": 1,
        "authorized_missing_codes_ref": {
            "relative_path": f"coverage/2026-10-16/input={SHA}/missing-codes.parquet",
            "file_sha256": SHA,
            "row_count": 1,
        },
        "authorization_run_id": "authorization-run",
    }


def test_recorded_results_keep_original_operation_authorization_after_gap_is_zero():
    wire = recorded_results_wire()
    wire["bootstrap_context"] = bootstrap_context_wire()
    record = models.parse_stk_factor_pro_record(
        models.StkFactorProRecordedResults, wire
    )
    assert record.raw_coverage.complete is True
    assert record.bootstrap_context.authorized_missing_count == 1
    assert record.bootstrap_context.authorized_missing_codes_ref.row_count == 1
    assert models.stk_factor_pro_record_to_dict(record) == wire


@pytest.mark.parametrize("kind", ["row_count", "bool_count", "run_reference", "target"])
def test_original_operation_authorization_rejects_wrong_reference_or_count(kind):
    wire = recorded_results_wire()
    wire["bootstrap_context"] = bootstrap_context_wire()
    if kind == "row_count":
        wire["bootstrap_context"]["authorized_missing_codes_ref"]["row_count"] = 2
    elif kind == "bool_count":
        wire["bootstrap_context"]["authorized_missing_codes_ref"]["row_count"] = True
    elif kind == "run_reference":
        wire["bootstrap_context"]["authorized_missing_codes_ref"] = reference(
            "diagnostics/day-missing-codes.parquet"
        )
    else:
        wire["bootstrap_context"]["target_trade_date"] = "2026-10-15"
    with pytest.raises((TypeError, ValueError)):
        models.parse_stk_factor_pro_record(models.StkFactorProRecordedResults, wire)


@pytest.mark.parametrize(
    "kind",
    [
        "target_day",
        "single_layer",
        "checkpoint_run",
        "source_run",
        "bool_count",
        "missing_scope",
        "unrefreshed",
        "order",
    ],
)
def test_publication_complete_rejects_wrong_date_layer_run_or_fields(kind):
    wire = publication_wire()
    if kind == "target_day":
        wire["targets"][0]["trade_date"] = "2026-10-16"
    elif kind == "single_layer":
        wire["targets"].pop()
    elif kind == "checkpoint_run":
        wire["targets"][0]["checkpoint_ref"]["creator_run_id"] = "other-run"
    elif kind == "source_run":
        wire["source_complete_ref"]["creator_run_id"] = "other-run"
    elif kind == "bool_count":
        wire["targets"][0]["file_rows"] = True
    elif kind == "missing_scope":
        wire["targets"][0]["scope_rows"] = None
    elif kind == "unrefreshed":
        wire["targets"][0]["unrefreshed_count"] = 1
    else:
        wire["targets"].reverse()
    with pytest.raises((TypeError, ValueError)):
        models.parse_stk_factor_pro_record(models.PublicationCompleteRecord, wire)


@pytest.mark.parametrize("kind", ["date", "raw_identity", "count", "unknown_field"])
def test_eligibility_rejects_mismatched_nested_evidence(kind):
    wire = eligibility_wire()
    if kind == "date":
        wire["raw_coverage"]["target_trade_date"] = "2026-10-15"
    elif kind == "raw_identity":
        wire["target_silver"]["current_raw_file_sha256"] = SILVER_SHA
        wire["target_silver"]["source_raw_file_sha256"] = SILVER_SHA
    elif kind == "count":
        wire["raw_coverage"]["expected_count"] = True
    else:
        wire["target_silver"]["passed"] = True
    with pytest.raises((TypeError, ValueError)):
        models.parse_stk_factor_pro_record(models.HistoryEligibilityRecord, wire)


def test_recorded_results_reject_wrong_target_and_duplicate_success_references():
    wire = recorded_results_wire()
    bad = deepcopy(wire)
    bad["raw_coverage"]["target_trade_date"] = "2026-10-15"
    with pytest.raises(ValueError):
        models.parse_stk_factor_pro_record(models.StkFactorProRecordedResults, bad)
    bad = deepcopy(wire)
    bad["successful_publication_refs"] *= 2
    with pytest.raises(ValueError):
        models.parse_stk_factor_pro_record(models.StkFactorProRecordedResults, bad)
