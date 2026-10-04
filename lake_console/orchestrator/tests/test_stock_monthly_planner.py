"""Frozen inventory drives bootstrap bounds; code batches never imply coverage."""

from dataclasses import asdict

import pytest

from orchestrator.defs.run_contracts.stock_monthly import (
    MonthlyYearInventory,
    StockMonthlyPolicy,
)
from orchestrator.defs.stock_monthly_planner import plan_month_bootstrap


def plan(inventories, **kwargs):
    return plan_month_bootstrap(
        "primary_unadjusted",
        inventories,
        first_month=kwargs.pop("first_month", "2020-02"),
        last_month=kwargs.pop("last_month", "2020-02"),
        inventory_ref=kwargs.pop("inventory_ref", "reports/frozen.json"),
        inventory_hash=kwargs.pop("inventory_hash", "a" * 64),
        **kwargs,
    )


def inventory(year=2020, codes=("000001.SZ", "600000.SH")):
    return MonthlyYearInventory(
        year, codes, ((f"{year}0228", len(codes)), ("20200229", len(codes)))
    )


def test_exclusion_counts_are_conserved_and_raw_request_range_keeps_both_versions():
    result = plan((inventory(),))
    assert (result.source_rows, result.excluded_rows, result.accepted_rows) == (4, 2, 2)
    assert result.months == ("2020-02",)
    assert (result.units[0].source_date_start, result.units[0].source_date_end) == (
        "2020-02-01",
        "2020-03-01",
    )
    assert result.units[0].max_rows == 4


def test_no_feb28_rows_does_not_create_feb29_fallback():
    result = plan((MonthlyYearInventory(2020, ("000001.SZ",), (("20200229", 1),)),))
    assert result.months == ()
    assert result.accepted_rows == 0
    assert result.excluded_rows == 1


def test_index_batch_units_are_disjoint_and_cover_each_inventory_code_once():
    codes = tuple(f"{i:06d}.SZ" for i in range(1, 302))
    result = plan((inventory(codes=codes),))
    assert [len(u.sorted_codes) for u in result.units] == [300, 1]
    assert tuple(c for u in result.units for c in u.sorted_codes) == codes
    assert len({u.unit_id for u in result.units}) == 2
    assert [u.max_rows for u in result.units] == [600, 2]


def test_source_inventory_evidence_and_policy_change_plan_identity():
    items = (inventory(),)
    original = plan(items)
    assert asdict(original) == asdict(plan(items))
    assert original.plan_hash != plan(items, inventory_hash="b" * 64).plan_hash
    assert (
        original.plan_hash
        != plan(items, policy=StockMonthlyPolicy(prod_code_batch=1)).plan_hash
    )
    adjusted = plan_month_bootstrap(
        "primary_adjusted",
        items,
        first_month="2020-02",
        last_month="2020-02",
        inventory_ref="reports/frozen.json",
        inventory_hash="a" * 64,
    )
    assert original.schema_hash != adjusted.schema_hash
    assert original.units[0].unit_id != adjusted.units[0].unit_id


def test_empty_year_is_explicit_and_not_a_missing_inventory():
    result = plan((MonthlyYearInventory(2020, (), ()),))
    assert result.units == () and result.months == () and result.source_rows == 0


@pytest.mark.parametrize(
    "items",
    [(), (inventory(), inventory()), (MonthlyYearInventory(2019, (), ()), inventory())],
)
def test_missing_duplicate_or_extra_year_refuses_plan(items):
    with pytest.raises(ValueError, match="year_inventory"):
        plan(items)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"first_month": "2020-03"},
        {"inventory_ref": ""},
        {"inventory_hash": "not-a-sha256"},
        {"inventory_hash": "X" * 64},
    ],
)
def test_invalid_scope_and_evidence_refuse_plan(kwargs):
    with pytest.raises(ValueError):
        plan((inventory(),), **kwargs)


def test_inventory_outside_partial_year_scope_refuses_plan():
    item = MonthlyYearInventory(
        2020, ("000001.SZ",), (("20200131", 1), ("20200228", 1))
    )
    with pytest.raises(ValueError, match="outside_scope"):
        plan((item,))


@pytest.mark.parametrize(
    "policy,reason",
    [
        (StockMonthlyPolicy(max_codes=1, prod_code_batch=1), "year_budget"),
        (StockMonthlyPolicy(max_year_rows=3), "year_budget"),
        (StockMonthlyPolicy(max_capture_rows=3), "capture_row_budget"),
        (StockMonthlyPolicy(max_prod_unit_rows=3), "unit_budget"),
    ],
)
def test_budget_rejection_never_silently_truncates(policy, reason):
    with pytest.raises(ValueError, match=reason):
        plan((inventory(),), policy=policy)


def test_last_partial_year_cannot_capture_later_months():
    item = MonthlyYearInventory(2026, ("000001.SZ",), (("20260930", 1),))
    result = plan((item,), first_month="2026-01", last_month="2026-09")
    assert result.units[0].source_date_end == "2026-10-01"
    assert result.months == ("2026-09",)
