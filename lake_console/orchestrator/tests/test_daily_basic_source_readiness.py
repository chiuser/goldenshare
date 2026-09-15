"""Daily-basic minimum coverage and bounded request counterexamples."""

from itertools import pairwise
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from orchestrator.defs.daily_basic_contract import (
    DAILY_BASIC_FIELDS,
    DailyBasicValidationError,
)
from orchestrator.defs.source_readiness.daily_basic import (
    fetch_daily_basic_pages,
    probe_daily_basic_for_trade_date,
)
from tests.test_daily_basic_raw_io import DAY, Source, row


class KeysSource(Source):
    def call(self, api, params, fields):
        result = super().call(api, params, fields)
        return SimpleNamespace(
            columns=fields, rows=[{key: r[key] for key in fields} for r in result.rows]
        )


def test_probe_extra_is_preserved_missing_is_capped():
    result = probe_daily_basic_for_trade_date(
        tushare=KeysSource([row(), row("000002.SZ")]),
        trade_date=DAY,
        expected_codes=["000001.SZ"],
    )
    assert result.ready and result.extra_count == 1
    result = probe_daily_basic_for_trade_date(
        tushare=KeysSource([]), trade_date=DAY, expected_codes=list("ABCDE")
    )
    assert (
        not result.ready
        and result.missing_count == 5
        and result.missing_samples == ("A", "B", "C")
    )


def test_request_count_and_retry_share_budget():
    now = [0.0]
    calls = []

    def request(api, params, fields):
        calls.append((now[0], params["offset"]))
        if len(calls) == 2:
            raise TimeoutError("network timeout")
        return SimpleNamespace(columns=fields, rows=[row(str(params["offset"]))])

    with (
        patch(
            "orchestrator.defs.source_readiness.daily_basic.DAILY_BASIC_PAGE_SIZE", 1
        ),
        pytest.raises(DailyBasicValidationError),
    ):
        fetch_daily_basic_pages(
            tushare=SimpleNamespace(call=request),
            trade_date=DAY,
            fields=DAILY_BASIC_FIELDS,
            consume_page=lambda *args: None,
            clock=lambda: now[0],
            sleep_fn=lambda s: now.__setitem__(0, now[0] + s),
        )
    assert len(calls) == 12
    assert calls[1][1] == calls[2][1]
    assert all(b[0] - a[0] >= 1 for a, b in pairwise(calls))


@pytest.mark.parametrize(
    "change", ["duplicate", "date", "null", "missing_field", "extra_field"]
)
def test_bad_source_never_completes(change):
    data = [row()]
    if change == "duplicate":
        data += [row()]
    elif change == "date":
        data[0]["trade_date"] = "20260911"
    elif change == "null":
        data[0]["ts_code"] = None
    elif change == "missing_field":
        del data[0]["close"]
    else:
        data[0]["source"] = "forbidden"
    with pytest.raises(DailyBasicValidationError):
        fetch_daily_basic_pages(
            tushare=Source(data),
            trade_date=DAY,
            fields=DAILY_BASIC_FIELDS,
            consume_page=lambda *args: None,
        )


def test_budget_after_last_consumer_is_rejected():
    now = [0.0]
    with pytest.raises(DailyBasicValidationError):
        fetch_daily_basic_pages(
            tushare=Source([row()]),
            trade_date=DAY,
            fields=DAILY_BASIC_FIELDS,
            consume_page=lambda *args: now.__setitem__(0, 60),
            clock=lambda: now[0],
        )
