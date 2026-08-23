from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.foundation.dao.news_stock_link_dao import NewsStockLinkDAO
from src.foundation.models.core_serving.news_stock_link import NewsStockLink


def test_news_stock_link_migration_is_chained_and_does_not_touch_source_views() -> None:
    migration = Path("alembic/versions/20260823_000145_add_news_stock_link.py").read_text(encoding="utf-8")

    assert 'revision = "20260823_000145"' in migration
    assert 'down_revision = "20260823_000144"' in migration
    assert "core_serving.news_stock_link" in migration
    assert "core_serving_light.news" not in migration
    assert "FOREIGN KEY" not in migration
    assert "channels" not in migration


def test_news_stock_link_dao_delete_and_upsert_are_idempotent() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS core_serving")
        NewsStockLink.__table__.create(connection)

    with Session(engine) as session:
        dao = NewsStockLinkDAO(session)
        row = {
            "news_id": "news-1",
            "ts_code": "000001.SZ",
            "match_method": "CODE_EXACT",
            "source_field": "title",
            "rule_version": "news-stock-rule-v1",
        }
        assert dao.bulk_upsert_current([row]) == 1
        session.commit()
        assert dao.existing_keys_by_news_ids(["news-1", "missing"]) == {("news-1", "000001.SZ")}
        assert dao.bulk_upsert_current([{**row, "match_method": "FULL_NAME_EXACT"}]) == 1
        session.commit()
        assert session.scalar(select(NewsStockLink.match_method)) == "FULL_NAME_EXACT"
        assert dao.delete_by_news_ids(["news-1", "news-1"]) == 1
        session.commit()
        assert session.scalar(select(NewsStockLink.news_id)) is None
