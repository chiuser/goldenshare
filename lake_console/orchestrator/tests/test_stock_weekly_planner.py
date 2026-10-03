from dataclasses import replace
from datetime import date

import pytest
from orchestrator.defs.run_contracts.stock_weekly import (
    ProdWeeklyScope,
    ProdYearInventory,
    StockWeeklySource,
    WeeklyAvailability,
    WeeklyBudget,
    WeeklyCandidate,
    WeeklyHistoryScope,
)
from orchestrator.defs.stock_weekly_planner import (
    freeze_prod_weekly_plan,
    freeze_weekly_history_plan,
    plan_prod_source_units,
    plan_weekly_source_units,
    source_date_week_key,
)


def scope(candidates, **kwargs):
    return WeeklyHistoryScope(
        "2010-01-01",
        "2026-10-09",
        tuple(candidates),
        "reports/expected.csv",
        "a" * 64,
        **kwargs,
    )


def candidate(key, availability=WeeklyAvailability.AVAILABLE, code="000005.SZ"):
    return WeeklyCandidate(code, key, availability, "reports/source.json", "d" * 64)


def test_iso_week_ownership_across_year_and_holiday():
    assert source_date_week_key("20091231") == "2010-01-01"
    assert source_date_week_key("20260924") == "2026-09-25"
    plan = plan_weekly_source_units(
        scope(
            [candidate("2010-01-01"), candidate("2010-12-31"), candidate("2011-01-07")]
        )
    )
    assert len(plan) == 2
    assert plan[0].request_start == date(2009, 12, 28)
    assert plan[0].request_end == date(2011, 1, 2)
    assert plan[0].expected_key_count == 2
    assert plan[0].max_rows == 53
    assert plan[1].request_start == date(2011, 1, 3)


def test_excluded_week_and_unavailable_candidates_stay_in_manifest_counts():
    s = scope(
        [
            candidate("2026-09-25"),
            candidate("2026-10-02"),
            candidate("2026-09-18", WeeklyAvailability.FAILED),
            candidate("2026-09-11", WeeklyAvailability.EMPTY_CONFIRMED),
            candidate("2026-09-04", WeeklyAvailability.IDENTITY_UNRESOLVED),
            candidate("2026-08-28", WeeklyAvailability.UNCHECKED),
        ],
        excluded_week_keys=("2026-10-02",),
    )
    plan = freeze_weekly_history_plan(s)
    assert plan.planned_key_count == 1 and plan.skipped_key_count == 5
    assert plan.request_cap == 3
    reasons = dict(plan.skipped_reason_counts)
    assert reasons["source_failed"] == reasons["source_empty_confirmed"] == 1
    assert reasons["source_unchecked"] == reasons["identity_unresolved"] == 1
    assert plan.units[0].request_end == date(2026, 9, 27)


def test_interior_exclusion_is_preserved_for_candidate_audit():
    p = plan_weekly_source_units(
        scope(
            [candidate("2026-09-25"), candidate("2026-10-09")],
            excluded_week_keys=("2026-10-02",),
        )
    )
    assert p[0].excluded_week_keys == ("2026-10-02",)


def test_plan_hash_is_deterministic_and_changes_with_evidence_or_budget():
    cs = [candidate("2026-09-25"), candidate("2026-09-18")]
    a = scope(cs)
    first = freeze_weekly_history_plan(a)
    assert first == freeze_weekly_history_plan(scope(list(reversed(cs))))
    assert (
        first.plan_hash
        != freeze_weekly_history_plan(replace(a, expected_key_hash="b" * 64)).plan_hash
    )
    assert (
        first.plan_hash
        != freeze_weekly_history_plan(
            replace(a, budget=WeeklyBudget(max_retries=0))
        ).plan_hash
    )


def test_invalid_scope_and_limits_are_not_silently_truncated():
    with pytest.raises(ValueError, match="duplicate_candidate"):
        scope([candidate("2026-09-25"), candidate("2026-09-25")])
    with pytest.raises(ValueError, match="candidate_key_budget"):
        scope(
            [candidate("2026-09-25"), candidate("2026-09-18")],
            budget=WeeklyBudget(max_candidate_keys=1),
        )
    with pytest.raises(ValueError, match="candidate_outside"):
        scope([candidate("2009-12-25")])
    with pytest.raises(ValueError, match="phase_file"):
        plan_weekly_source_units(
            scope(
                [candidate("2026-09-25"), candidate("2026-09-18")],
                budget=WeeklyBudget(max_phase_files=1),
            )
        )
    with pytest.raises(ValueError):
        WeeklyCandidate(
            "000005.SZ,000001.SZ", "2026-09-25", WeeklyAvailability.AVAILABLE
        )


def test_available_and_confirmed_empty_need_actual_evidence_reference():
    for status in (WeeklyAvailability.AVAILABLE, WeeklyAvailability.EMPTY_CONFIRMED):
        with pytest.raises(ValueError, match="requires_source_evidence"):
            WeeklyCandidate("000005.SZ", "2026-09-25", status)
    p = plan_weekly_source_units(scope([candidate("2026-09-25")]))
    assert p[0].source_evidence == (("reports/source.json", "d" * 64),)


def test_confirmed_unavailable_does_not_prevent_recorded_partial_completion():
    p = freeze_weekly_history_plan(
        scope([candidate("2026-09-25", WeeklyAvailability.EMPTY_CONFIRMED)])
    )
    assert not p.units and p.request_cap == 0
    assert p.skipped_key_count == 1 and dict(p.skipped_reason_counts) == {
        "source_empty_confirmed": 1
    }


def prod_scope(inventories, **kwargs):
    return ProdWeeklyScope(
        StockWeeklySource.PRIMARY_UNADJUSTED,
        tuple(inventories),
        "reports/inventory.csv",
        "c" * 64,
        **kwargs,
    )


def test_prod_is_code_batch_by_source_year_and_keeps_pre_2010_history():
    codes = tuple(f"{x:06d}.SZ" for x in range(301))
    s = prod_scope(
        [
            ProdYearInventory(2009, ("000005.SZ",), 1),
            ProdYearInventory(2025, codes, 15_652),
        ]
    )
    units = plan_prod_source_units(s)
    assert len(units) == 3
    assert units[0].source_date_start == date(2009, 1, 1)
    assert units[0].source_date_end == date(2010, 1, 1)
    assert [len(u.sorted_codes) for u in units] == [1, 300, 1]
    assert set(units[1].sorted_codes).isdisjoint(units[2].sorted_codes)
    assert len({u.unit_id for u in units}) == 3
    assert freeze_prod_weekly_plan(s).planned_key_count == 15_653
    assert freeze_prod_weekly_plan(s).request_cap == 0


def test_smaller_prod_budget_splits_plan_before_execution():
    s = prod_scope(
        [ProdYearInventory(2025, ("000001.SZ", "000002.SZ"), 104)],
        budget=WeeklyBudget(max_source_rows_per_prod_unit=54, fetch_batch_rows=54),
    )
    assert len(plan_prod_source_units(s)) == 2
    assert all(u.max_rows == 54 for u in plan_prod_source_units(s))


def test_prod_inventory_rejects_alternate_and_duplicate_or_mutable_input():
    with pytest.raises(ValueError, match="alternate_has_no_prod"):
        ProdWeeklyScope(StockWeeklySource.ALTERNATE_WEEKLY, (), "x", "a" * 64)
    with pytest.raises(ValueError, match="duplicate_inventory_code"):
        ProdYearInventory(2025, ("000001.SZ", "000001.SZ"), 100)
    original = ["000005.SZ"]
    inv = ProdYearInventory(2020, original, 52)
    original.append("000001.SZ")
    assert inv.codes == ("000005.SZ",)
    with pytest.raises(ValueError, match="phase_row"):
        prod_scope([inv], budget=WeeklyBudget(max_phase_rows=51))


@pytest.mark.parametrize("value", ["2026-09-25", "20260230", "2026092", True])
def test_source_dates_reject_non_source_formats(value):
    with pytest.raises(ValueError):
        source_date_week_key(value)
