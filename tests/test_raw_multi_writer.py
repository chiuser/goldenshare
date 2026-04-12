from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.foundation.dao.raw_multi_writer import RAW_MULTI_DAO_NAME, RawMultiWriter


class _DummyDao:
    def __init__(self, result: int) -> None:
        self.result = result
        self.rows = None

    def bulk_upsert(self, rows):  # type: ignore[no-untyped-def]
        self.rows = rows
        return self.result


def test_raw_multi_writer_routes_to_expected_dao() -> None:
    daily_dao = _DummyDao(result=3)
    dao_factory = SimpleNamespace(raw_tushare_equity_daily_bar=daily_dao)
    writer = RawMultiWriter(dao_factory)  # type: ignore[arg-type]

    written = writer.bulk_upsert("tushare", "equity_daily_bar", [{"ts_code": "000001.SZ", "trade_date": "20260412"}])

    assert written == 3
    assert daily_dao.rows == [{"ts_code": "000001.SZ", "trade_date": "20260412"}]


def test_raw_multi_writer_rejects_unknown_route() -> None:
    writer = RawMultiWriter(SimpleNamespace())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Unsupported raw multi route"):
        writer.bulk_upsert("unknown", "equity_daily_bar", [])


def test_raw_multi_writer_route_map_covers_expected_pairs() -> None:
    expected_pairs = {
        ("tushare", "equity_daily_bar"),
        ("biying", "equity_daily_bar"),
        ("tushare", "equity_adj_factor"),
        ("biying", "equity_adj_factor"),
        ("tushare", "equity_daily_basic"),
        ("biying", "equity_daily_basic"),
        ("tushare", "stock_basic"),
        ("biying", "stock_basic"),
    }
    assert expected_pairs.issubset(set(RAW_MULTI_DAO_NAME.keys()))
