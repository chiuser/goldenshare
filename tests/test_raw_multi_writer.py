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
    dao_factory = SimpleNamespace(raw_stock_basic=daily_dao)
    writer = RawMultiWriter(dao_factory)  # type: ignore[arg-type]

    written = writer.bulk_upsert("tushare", "stock_basic", [{"ts_code": "000001.SZ"}])

    assert written == 3
    assert daily_dao.rows == [{"ts_code": "000001.SZ"}]


def test_raw_multi_writer_rejects_unknown_route() -> None:
    writer = RawMultiWriter(SimpleNamespace())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="不支持的多来源原始写入路径"):
        writer.bulk_upsert("unknown", "stock_basic", [])


def test_raw_multi_writer_route_map_covers_expected_pairs() -> None:
    expected_pairs = {
        ("tushare", "stock_basic"),
        ("biying", "stock_basic"),
    }
    assert expected_pairs.issubset(set(RAW_MULTI_DAO_NAME.keys()))
