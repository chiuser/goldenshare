from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.foundation.dao.base_dao import BaseDAO
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


def test_news_stock_link_dao_persists_mixed_existing_and_new_rows() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS core_serving")
        NewsStockLink.__table__.create(connection)

    preserved_created_at = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    existing_row = {
        "news_id": "existing-news",
        "ts_code": "300308.SZ",
        "match_method": "SHORT_NAME_EXACT",
        "source_field": "title",
        "rule_version": "news-stock-rule-v1",
        "created_at": preserved_created_at,
    }
    new_row = {
        "news_id": "new-news",
        "ts_code": "300308.SZ",
        "match_method": "CODE_EXACT",
        "source_field": "content",
        "rule_version": "news-stock-rule-v1",
    }

    with Session(engine) as session:
        dao = NewsStockLinkDAO(session)
        assert dao.bulk_upsert_current([existing_row, new_row]) == 2
        session.commit()
        created_at_by_news_id = dict(
            session.execute(
                select(NewsStockLink.news_id, NewsStockLink.created_at).order_by(NewsStockLink.news_id)
            ).all()
        )

    assert created_at_by_news_id["existing-news"] == preserved_created_at.replace(tzinfo=None)
    assert created_at_by_news_id["new-news"] is not None
    assert "created_at" not in new_row


def test_news_stock_link_dao_produces_uniform_rows_for_postgres_multirow_insert(monkeypatch) -> None:
    preserved_created_at = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    captured: dict[str, object] = {}

    def capture_bulk_upsert(self, rows, conflict_columns=None):  # type: ignore[no-untyped-def]
        captured["rows"] = rows
        captured["conflict_columns"] = conflict_columns
        return len(rows)

    monkeypatch.setattr(BaseDAO, "bulk_upsert", capture_bulk_upsert)
    with Session() as session:
        dao = NewsStockLinkDAO(session)
        assert dao.bulk_upsert_current(
            [
                {
                    "news_id": "existing-news",
                    "ts_code": "300308.SZ",
                    "match_method": "SHORT_NAME_EXACT",
                    "source_field": "title",
                    "rule_version": "news-stock-rule-v1",
                    "created_at": preserved_created_at,
                },
                {
                    "news_id": "new-news",
                    "ts_code": "300308.SZ",
                    "match_method": "CODE_EXACT",
                    "source_field": "content",
                    "rule_version": "news-stock-rule-v1",
                },
            ]
        ) == 2

    normalized_rows = captured["rows"]
    assert isinstance(normalized_rows, list)
    assert {frozenset(row) for row in normalized_rows} == {
        frozenset(
            {
                "news_id",
                "ts_code",
                "match_method",
                "source_field",
                "rule_version",
                "created_at",
            }
        )
    }
    assert normalized_rows[0]["created_at"] == preserved_created_at
    assert normalized_rows[1]["created_at"] is not None
    assert captured["conflict_columns"] == ["news_id", "ts_code"]

    insert(NewsStockLink).values(normalized_rows).compile(dialect=postgresql.dialect())
