from datetime import date
from decimal import Decimal

import pytest

from orchestrator.defs.run_contracts.stock_period import (
    FIELDS,
    period_for,
    request_params,
    validate_rows,
)


def row(code="000001.SZ", day="20261016", freq="week", value="1.2500"):
    return [code, day, "20261015", freq] + [Decimal(value)] * 17


def test_history_no_dates_and_new_code_only():
    scope = {"920000.BJ"}
    aliases = {"832000.BJ": "920000.BJ", "920000.BJ": "920000.BJ"}
    assert request_params(
        freq="week", code="920000.BJ", listed=scope, aliases=aliases
    ) == {"freq": "week", "limit": 6000, "offset": 0, "ts_code": "920000.BJ"}
    for code in ["832000.BJ", "999999.SZ", "920001.BJ"]:
        with pytest.raises(ValueError):
            request_params(freq="month", code=code, listed=scope, aliases=aliases)


def test_month_preserves_both_source_dates_and_null():
    a = row(day="20200228", freq="month")
    b = row(day="20200229", freq="month")
    a[9] = None
    assert len(validate_rows(FIELDS, [a, b], freq="month", period="2020-02")) == 2
    assert request_params(freq="month", period="2020-02")["end_date"] == "20200229"
    assert request_params(freq="month", period="2020-02")["start_date"] == "20200201"
    assert period_for(date(2026, 10, 12), "week") == "2026-10-16"


@pytest.mark.parametrize(
    "change", ["field", "precision", "duplicate", "freq", "date", "identity"]
)
def test_wire_rejects_true_errors(change):
    fields = list(FIELDS)
    items = [row()]
    if change == "field":
        fields.pop()
    elif change == "precision":
        items[0][5] = Decimal("1.23456")
    elif change == "duplicate":
        items *= 2
    elif change == "freq":
        items[0][3] = "month"
    elif change == "date":
        items[0][1] = "20260230"
    elif change == "identity":
        items[0][0] = "920000.BJ"
    with pytest.raises(ValueError):
        validate_rows(fields, items, freq="week", code="000001.SZ")
