from __future__ import annotations

from src.foundation.normalization.equity_adj_factor_normalizer import EquityAdjFactorNormalizer


def test_normalizer_error_isolation_keeps_valid_rows() -> None:
    normalizer = EquityAdjFactorNormalizer()
    rows, errors = normalizer.normalize_rows(
        [
            {"ts_code": "000001.SZ", "trade_date": "20260412", "adj_factor": "1.234"},
            {"ts_code": "000002.SZ", "trade_date": "20260412"},
            {"trade_date": "20260412", "adj_factor": "2.0"},
        ],
        source_key="tushare",
    )

    assert len(rows) == 1
    assert rows[0]["ts_code"] == "000001.SZ"
    assert len(errors) == 2
    assert errors[0].index == 1
    assert errors[1].index == 2
