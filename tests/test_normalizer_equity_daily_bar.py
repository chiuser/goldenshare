from __future__ import annotations

from decimal import Decimal

from src.foundation.normalization.equity_daily_bar_normalizer import EquityDailyBarNormalizer


def test_equity_daily_bar_normalizer_maps_change_to_change_amount() -> None:
    normalizer = EquityDailyBarNormalizer()
    rows, errors = normalizer.normalize_rows(
        [
            {
                "ts_code": "000001.SZ",
                "trade_date": "20260412",
                "open": "10.01",
                "close": "10.11",
                "change": "0.10",
                "pct_chg": "0.99",
            }
        ],
        source_key="tushare",
    )

    assert errors == []
    assert len(rows) == 1
    assert rows[0]["source_key"] == "tushare"
    assert rows[0]["trade_date"].isoformat() == "2026-04-12"
    assert rows[0]["change_amount"] == Decimal("0.10")
    assert rows[0]["open"] == Decimal("10.01")


def test_equity_daily_bar_normalizer_reports_missing_required_fields() -> None:
    normalizer = EquityDailyBarNormalizer()
    rows, errors = normalizer.normalize_rows([{"trade_date": "20260412"}], source_key="tushare")

    assert rows == []
    assert len(errors) == 1
    assert "missing required fields: ts_code" in errors[0].reason
