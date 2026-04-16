from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from src.operations.services.indicator_state_reconcile_service import IndicatorStateReconcileService


def test_indicator_state_reconcile_service_detects_missing_and_mismatch(mocker) -> None:
    session = mocker.Mock()
    session.execute.side_effect = [
        SimpleNamespace(
            all=lambda: [
                SimpleNamespace(ts_code="000001.SZ", latest_trade_date=date(2026, 4, 10), bar_count=100),
                SimpleNamespace(ts_code="000002.SZ", latest_trade_date=date(2026, 4, 11), bar_count=80),
            ]
        ),
        SimpleNamespace(
            all=lambda: [
                SimpleNamespace(ts_code="000001.SZ", adj_factor=Decimal("1.20000000")),
                SimpleNamespace(ts_code="000002.SZ", adj_factor=Decimal("2.00000000")),
            ]
        ),
    ]
    session.scalars.return_value = [
        SimpleNamespace(
            ts_code="000001.SZ",
            adjustment="forward",
            indicator_name="macd",
            last_trade_date=date(2026, 4, 10),
            state_json={"bar_count": 99, "last_adj_factor": 1.0},
        ),
        SimpleNamespace(
            ts_code="000001.SZ",
            adjustment="forward",
            indicator_name="kdj",
            last_trade_date=date(2026, 4, 10),
            state_json={"bar_count": 100},
        ),
        SimpleNamespace(
            ts_code="000001.SZ",
            adjustment="forward",
            indicator_name="rsi",
            last_trade_date=date(2026, 4, 10),
            state_json={"bar_count": 100},
        ),
        SimpleNamespace(
            ts_code="000001.SZ",
            adjustment="backward",
            indicator_name="macd",
            last_trade_date=date(2026, 4, 9),
            state_json={"bar_count": 99, "last_adj_factor": 1.2},
        ),
        SimpleNamespace(
            ts_code="000001.SZ",
            adjustment="backward",
            indicator_name="rsi",
            last_trade_date=date(2026, 4, 10),
            state_json={"bar_count": 100},
        ),
    ]

    report = IndicatorStateReconcileService().run(
        session,
        source_key="tushare",
        version=1,
        sample_limit=5,
    )

    assert report.total_codes == 2
    assert report.expected_states == 12
    assert report.existing_states == 5
    assert report.missing_state == 7
    assert report.stale_state == 1
    assert report.bar_count_mismatch == 1
    assert report.adj_factor_mismatch == 1
    assert report.has_issue is True
    assert report.samples["missing_state"][0].issue_type == "missing_state"
    assert report.samples["stale_state"][0].issue_type == "stale_state"
    assert report.samples["bar_count_mismatch"][0].issue_type == "bar_count_mismatch"
    assert report.samples["adj_factor_mismatch"][0].issue_type == "adj_factor_mismatch"


def test_indicator_state_reconcile_service_empty_dataset(mocker) -> None:
    session = mocker.Mock()
    session.execute.return_value = SimpleNamespace(all=lambda: [])

    report = IndicatorStateReconcileService().run(session)

    assert report.total_codes == 0
    assert report.expected_states == 0
    assert report.existing_states == 0
    assert report.has_issue is False
