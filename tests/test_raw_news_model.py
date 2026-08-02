from __future__ import annotations

from src.foundation.models.raw.raw_news import RawNews


def test_raw_news_restores_the_single_table_identity() -> None:
    table = RawNews.__table__

    assert "id" in table.c
    assert [column.name for column in table.primary_key.columns] == ["id"]
    indexes = {index.name: index for index in table.indexes}
    assert set(indexes) == {
        "uq_raw_tushare_news_row_key_hash",
        "idx_raw_tushare_news_src_time",
        "idx_raw_tushare_news_time",
    }
    assert indexes["uq_raw_tushare_news_row_key_hash"].unique
