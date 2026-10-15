from datetime import date

import pytest
from orchestrator.defs.run_contracts.stock_weekly import (
    ProdWeeklyScope,
    ProdYearInventory,
    StockWeeklySource,
    WeeklyBudget,
)
from orchestrator.defs.stock_weekly_planner import (
    freeze_prod_weekly_plan,
    plan_prod_source_units,
    source_date_week_key,
)


def prod_scope(inventories, **kwargs):
    return ProdWeeklyScope(
        StockWeeklySource.PRIMARY_ADJUSTED,
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
    with pytest.raises(ValueError):
        ProdWeeklyScope("weekly", (), "x", "a" * 64)
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
