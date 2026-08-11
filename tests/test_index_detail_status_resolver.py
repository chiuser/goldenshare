from __future__ import annotations

from datetime import date

from src.biz.services.wealth.market.index_detail.index_detail_status_resolver import IndexDetailStatusResolver


def test_status_priority_is_empty_then_partial_then_delayed_then_ready() -> None:
    resolver = IndexDetailStatusResolver()
    expected = date(2026, 8, 10)
    observed = date(2026, 8, 7)

    assert resolver.resolve(
        expected_trade_date=expected,
        observed_trade_date=observed,
        empty=True,
        partial=True,
    ).status == "EMPTY"
    assert resolver.resolve(
        expected_trade_date=expected,
        observed_trade_date=observed,
        empty=False,
        partial=True,
    ).status == "PARTIAL"
    assert resolver.resolve(
        expected_trade_date=expected,
        observed_trade_date=observed,
        empty=False,
        partial=False,
    ).status == "DELAYED"
    assert resolver.resolve(
        expected_trade_date=expected,
        observed_trade_date=expected,
        empty=False,
        partial=False,
    ).status == "READY"
