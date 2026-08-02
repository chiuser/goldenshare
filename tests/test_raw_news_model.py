from __future__ import annotations

from src.foundation.models.raw.raw_news import RawNews


def test_raw_news_uses_partition_compatible_composite_identity() -> None:
    table = RawNews.__table__

    assert "id" not in table.c
    assert [column.name for column in table.primary_key.columns] == ["news_time", "row_key_hash"]
    assert {index.name for index in table.indexes} == {
        "idx_raw_tushare_news_src_time",
        "idx_raw_tushare_news_time",
    }
