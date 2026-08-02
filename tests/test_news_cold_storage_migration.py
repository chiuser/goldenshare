from __future__ import annotations

from pathlib import Path


_MIGRATION_PATH = Path("alembic/versions/20260802_000121_prepare_news_cold_storage.py")


def test_news_cold_storage_migration_only_prepares_empty_stage() -> None:
    content = _MIGRATION_PATH.read_text(encoding="utf-8")
    normalized = " ".join(content.lower().split())

    assert 'down_revision = "20260801_000120"' in content
    assert "CREATE TABLE raw_tushare.news_partitioned_stage" in content
    assert "PARTITION BY RANGE (news_time)" in content
    assert "range(2022, 2031)" in content
    assert "gs_raw_cold_hdd" in content
    assert "insert into raw_tushare.news_partitioned_stage" not in normalized
    assert "drop table raw_tushare.news" not in normalized
    assert "alter table raw_tushare.news rename" not in normalized
    assert "create or replace view core_serving_light.news" not in normalized
