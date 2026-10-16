"""Retained monthly schema and actual direct-source range/date contract."""

import pytest

from orchestrator.defs.run_contracts.stock_monthly import (
    StockMonthlySource,
    monthly_column_specs,
    monthly_source_api,
    normalize_month_key,
)
from orchestrator.defs.run_contracts.stock_period import period_date, request_params


@pytest.mark.parametrize(
    "month,anchor",
    [
        ("2020-02", "20200229"),
        ("2024-02", "20240229"),
        ("2026-05", "20260531"),
        ("2026-09", "20260930"),
        ("2026-12", "20261231"),
        ("0001-01", "00010131"),
    ],
)
def test_current_request_uses_whole_calendar_month(month, anchor):
    assert period_date(month, "month") == anchor
    assert request_params(freq="month", period=month) == {
        "freq": "month",
        "limit": 6000,
        "offset": 0,
        "start_date": anchor[:6] + "01",
        "end_date": anchor,
    }


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


def test_source_schema_is_business_projection():
    source = StockMonthlySource.PRIMARY_ADJUSTED
    specs = monthly_column_specs(source)
    assert monthly_source_api(source) == "stk_week_month_adj" and len(specs) == 21
    assert specs[:4] == (
        ("ts_code", "VARCHAR"),
        ("trade_date", "VARCHAR"),
        ("end_date", "VARCHAR"),
        ("freq", "VARCHAR"),
    )
    assert dict(specs)["close"] == "DECIMAL(18,4)"
    assert dict(specs)["vol"] == "DECIMAL(20,4)"
    assert dict(specs)["pct_chg"] == "DECIMAL(10,4)"
    assert {"close_qfq", "close_hfq"} <= dict(specs).keys()
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


@pytest.mark.parametrize("source", ["weekly", "monthly", "unknown"])
def test_alternate_source_cannot_enter_month_contract(source):
    with pytest.raises(ValueError):
        monthly_source_api(source)


def test_current_builder_does_not_retain_old_four_page_cap():
    params = request_params(freq="month", period="2020-02", offset=24000)
    assert params == {
        "freq": "month",
        "limit": 6000,
        "offset": 24000,
        "start_date": "20200201",
        "end_date": "20200229",
    }
    assert "trade_date" not in params
