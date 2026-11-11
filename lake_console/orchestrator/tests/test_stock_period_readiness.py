"""LLD13 literal code/date cases. Source fields follow doc365 and the 2026-11-11 HTTP evidence."""

import json
from dataclasses import replace
from datetime import datetime

import pytest

from orchestrator.defs.run_contracts.stock_period import DEFAULT_POLICY, request_params
from orchestrator.defs.source_readiness import stock_period as readiness

A, NEW, SUSPENDED = "000001.SZ", "301393.SZ", "000002.SZ"
D = "2026-11-10"


@pytest.mark.parametrize("freq,label", [("week", "20261113"), ("month", "20261130")])
@pytest.mark.parametrize("optional", [None, "20261109", "20261110"])
def test_required_new_listing_and_optional_full_day_suspend(freq, label, optional):
    rows = [[A, label, "20261110"], [NEW, label, "20261110"]]
    if optional is not None:
        rows.append([SUSPENDED, label, optional])
    result = readiness.check_period_rows(
        rows,
        freq=freq,
        business_date=D,
        required_codes={A, NEW},
        optional_codes={SUSPENDED},
        aliases={},
    )
    assert result["ready"] and result["returned_required_count"] == 2
    assert result["returned_optional_count"] == int(optional is not None)


@pytest.mark.parametrize(
    "case",
    [
        "missing_new",
        "same_count_wrong_code",
        "stale",
        "duplicate",
        "optional_not_a_substitute",
    ],
)
def test_incomplete_required_codes_do_not_pass(case):
    rows = [[A, "20261113", "20261110"], [NEW, "20261113", "20261110"]]
    if case == "missing_new":
        rows.pop()
    if case == "same_count_wrong_code":
        rows[1][0] = "999999.SZ"
    if case == "stale":
        rows[1][2] = "20261109"
    if case == "duplicate":
        rows.append(list(rows[0]))
    if case == "optional_not_a_substitute":
        rows[1][0] = SUSPENDED
    result = readiness.check_period_rows(
        rows,
        freq="week",
        business_date=D,
        required_codes={A, NEW},
        optional_codes={SUSPENDED},
        aliases={},
    )
    assert not result["ready"]


@pytest.mark.parametrize(
    "row",
    [
        [A, "20261112", "20261110"],
        [A, "20261113", "20261111"],
        [A, "20261113", None],
        [A, "20261113", "20260230"],
    ],
)
def test_bad_label_future_or_invalid_date_rejected(row):
    with pytest.raises(ValueError):
        readiness.check_period_rows(
            [row],
            freq="week",
            business_date=D,
            required_codes={A},
            optional_codes=set(),
            aliases={},
        )


def envelope(items, fields=None):
    return json.dumps(
        {
            "code": 0,
            "data": {
                "fields": fields or ["ts_code", "trade_date", "end_date"],
                "items": items,
            },
        }
    ).encode()


def test_paging_one_deadline_no_reset_and_expiry(monkeypatch):
    monkeypatch.setattr(
        readiness, "DEFAULT_POLICY", replace(DEFAULT_POLICY, page_limit=1)
    )
    clock = [10.0]
    monkeypatch.setattr(readiness.time, "monotonic", lambda: clock[0])
    calls = []

    def transport(params, *, deadline):
        calls.append((dict(params), deadline))
        clock[0] += 0.5
        return envelope([[A, "20261113", "20261110"]] if params["offset"] == 0 else [])

    kwargs = {
        "freq": "week",
        "business_date": D,
        "required_codes": {A},
        "optional_codes": set(),
        "aliases": {},
        "transport": transport,
    }
    assert readiness.probe_stock_period_source(**kwargs, deadline=12)["ready"]
    assert [params["offset"] for params, _ in calls] == [0, 1]
    assert {deadline for _, deadline in calls} == {12}
    calls.clear()
    clock[0] = 10
    assert not readiness.probe_stock_period_source(**kwargs, deadline=10.75)["ready"]
    assert len(calls) == 2
    calls.clear()
    assert not readiness.probe_stock_period_source(**kwargs, deadline=10)["ready"]
    assert not calls


@pytest.mark.parametrize("mode", ["fields", "repeat", "api", "exception"])
def test_probe_failures_wait_instead_of_submit(monkeypatch, mode):
    monkeypatch.setattr(
        readiness, "DEFAULT_POLICY", replace(DEFAULT_POLICY, page_limit=1)
    )
    calls = []

    def transport(params, *, deadline):
        calls.append(params)
        if mode == "fields":
            return envelope([], fields=["ts_code"])
        if mode == "api":
            return b'{"code":-1}'
        if mode == "exception":
            raise ConnectionError("HTTP failure")
        return envelope([[A, "20261113", "20261110"]])

    result = readiness.probe_stock_period_source(
        freq="week",
        business_date=D,
        required_codes={A},
        optional_codes=set(),
        aliases={},
        transport=transport,
        deadline=readiness.time.monotonic() + 30,
    )
    assert not result["ready"] and len(calls) == (2 if mode == "repeat" else 1)


def test_point_requests_and_history_inputs_have_distinct_semantics():
    assert request_params(freq="week", period="2026-11-13") == {
        "freq": "week",
        "trade_date": "20261113",
        "offset": 0,
        "limit": 6000,
    }
    assert request_params(freq="month", period="2026-11") == {
        "freq": "month",
        "trade_date": "20261130",
        "offset": 0,
        "limit": 6000,
    }
    assert request_params(freq="month", code=A, listed={A}) == {
        "freq": "month",
        "ts_code": A,
        "offset": 0,
        "limit": 6000,
    }


def test_sensor_time_gate_is_20_shanghai_before_any_input_access():
    from orchestrator.defs.stock_period_update import evaluate_daily_sensor

    for freq in ("week", "month"):
        result = evaluate_daily_sensor(
            None, datetime.fromisoformat("2026-11-10T19:59:59+08:00"), freq=freq
        )
        assert not result.run_requests and "20:00" in result.skip_reason.skip_message
