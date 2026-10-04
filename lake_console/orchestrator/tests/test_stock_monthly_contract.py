"""Date/version, source schema and bounded request contract acceptance."""

from dataclasses import FrozenInstanceError
from datetime import date

import pytest

from orchestrator.defs.run_contracts.stock_monthly import (
    MonthlyDateDisposition,
    MonthlyYearInventory,
    StockMonthlyPolicy,
    StockMonthlySource,
    classify_month_date,
    month_window,
    monthly_column_specs,
    monthly_point_request,
    monthly_source_api,
    normalize_month_key,
    request_date_for_month,
)


@pytest.mark.parametrize(
    "month,anchor",
    [
        ("2020-02", "20200228"),
        ("2024-02", "20240229"),
        ("2026-05", "20260531"),
        ("2026-09", "20260930"),
        ("2026-12", "20261231"),
        ("0001-01", "00010131"),
    ],
)
def test_month_anchor_preserves_exception_and_calendar_month_end(month, anchor):
    assert request_date_for_month(month) == anchor
    assert classify_month_date(anchor) == (month, MonthlyDateDisposition.ACCEPTED)


@pytest.mark.parametrize(
    "value",
    [
        "2026-5",
        "20260531",
        "2026-05-31",
        "2026-00",
        "2026-13",
        "0000-01",
        "２０２６-０５",
        True,
        None,
    ],
)
def test_non_month_input_is_rejected(value):
    with pytest.raises(ValueError):
        normalize_month_key(value)


def test_year_end_window_is_half_open():
    assert month_window("2026-12") == (date(2026, 12, 1), date(2027, 1, 1))


@pytest.mark.parametrize(
    "value",
    ["20260529", "20240228", "20200227", "20260229", "2026-05-31", "２０２６０５３１"],
)
def test_unapproved_date_variants_are_rejected(value):
    with pytest.raises(ValueError):
        classify_month_date(value)


def test_feb29_is_explicit_exclusion_not_remapped_or_accepted():
    assert classify_month_date("20200229") == (
        "2020-02",
        MonthlyDateDisposition.EXCLUDED_VERSION,
    )
    inventory = MonthlyYearInventory(
        2020, ("000001.SZ",), (("20200228", 1), ("20200229", 1))
    )
    assert (inventory.source_rows, inventory.excluded_rows) == (2, 1)


@pytest.mark.parametrize(
    "source,api,columns",
    [
        (StockMonthlySource.PRIMARY_UNADJUSTED, "stk_weekly_monthly", 13),
        (StockMonthlySource.PRIMARY_ADJUSTED, "stk_week_month_adj", 21),
    ],
)
def test_source_schema_is_business_projection(source, api, columns):
    specs = monthly_column_specs(source)
    assert monthly_source_api(source) == api
    assert len(specs) == columns
    assert specs[:4] == (
        ("ts_code", "VARCHAR"),
        ("trade_date", "VARCHAR"),
        ("end_date", "VARCHAR"),
        ("freq", "VARCHAR"),
    )
    assert dict(specs)["close"] == "DECIMAL(18,4)"
    assert dict(specs)["vol"] == "DECIMAL(20,4)"
    assert dict(specs)["pct_chg"] == "DECIMAL(10,4)"
    assert (
        not {
            "api_name",
            "fetched_at",
            "raw_payload",
            "source",
            "created_at",
            "updated_at",
        }
        & dict(specs).keys()
    )
    assert ("close_qfq" in dict(specs)) == (columns == 21)


@pytest.mark.parametrize("source", ["weekly", "monthly", "unknown"])
def test_alternate_source_cannot_enter_month_contract(source):
    with pytest.raises(ValueError):
        monthly_source_api(source)


def test_request_builder_owns_frequency_anchor_and_offset():
    policy = StockMonthlyPolicy(page_limit=5)
    assert monthly_point_request("2020-02", 1, policy) == {
        "freq": "month",
        "trade_date": "20200228",
        "limit": 5,
        "offset": 5,
    }
    assert monthly_point_request("2026-05", 0, policy)["trade_date"] == "20260531"


@pytest.mark.parametrize("page", [-1, 4, True, 0.5])
def test_request_cannot_exceed_page_cap(page):
    with pytest.raises(ValueError, match="page_budget"):
        monthly_point_request("2026-05", page, StockMonthlyPolicy())


@pytest.mark.parametrize(
    "kwargs",
    [
        {"prod_code_batch": 0},
        {"page_limit": 6001},
        {"max_retries": -1},
        {"max_pages": True},
        {"max_codes": 20},
        {"max_update_rows": 5999},
    ],
)
def test_budget_rejects_invalid_values_and_conflicting_limits(kwargs):
    with pytest.raises(ValueError):
        StockMonthlyPolicy(**kwargs)


def test_inventory_detaches_mutable_inputs_and_is_frozen():
    codes = ["000001.SZ"]
    counts = [["20200228", 1]]
    inventory = MonthlyYearInventory(2020, codes, counts)
    codes.append("600000.SH")
    counts[0][1] = 99
    assert inventory.codes == ("000001.SZ",)
    assert inventory.source_date_counts == (("20200228", 1),)
    with pytest.raises(FrozenInstanceError):
        inventory.year = 2021


@pytest.mark.parametrize(
    "year,codes,counts",
    [
        (True, ("000001.SZ",), (("20200228", 1),)),
        (2020, ("000001.SZ", "000001.SZ"), (("20200228", 1),)),
        (2020, ("000001",), (("20200228", 1),)),
        (2020, ("000001.SZ",), (("20200228", True),)),
        (2020, ("000001.SZ",), (("20200228", 2),)),
        (2020, ("000001.SZ",), (("20200228", 1), ("20200228", 1))),
        (2020, ("000001.SZ",), (("20210531", 1),)),
        (2020, ("000001.SZ",), ()),
    ],
)
def test_inventory_rejects_unclosed_or_invalid_scope(year, codes, counts):
    with pytest.raises(ValueError):
        MonthlyYearInventory(year, codes, counts)
