from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.foundation.dao.news_stock_link_dao import NewsStockLinkDAO
from src.foundation.models.core_serving.news_stock_link import NewsStockLink
from src.foundation.models.core_serving.security_serving import Security
from src.foundation.models.core_serving_light.namechange import NamechangeLight
from src.foundation.models.core_serving_light.news import NewsLight
from src.ops.services.news_stock_linking_service import NewsStockLinkingService


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS core_serving")
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS core_serving_light")
        for table in (Security.__table__, NewsStockLink.__table__, NamechangeLight.__table__, NewsLight.__table__):
            table.create(connection, checkfirst=True)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def _seed(session_factory, base_time: datetime) -> None:
    with session_factory() as session:
        session.add_all(
            [
                Security(
                    ts_code="000001.SZ",
                    symbol="000001",
                    name="平安银行",
                    fullname="平安银行股份有限公司",
                    security_type="EQUITY",
                    source="tushare",
                ),
                Security(
                    ts_code="600519.SH",
                    symbol="600519",
                    name="贵州茅台",
                    fullname="贵州茅台酒股份有限公司",
                    security_type="EQUITY",
                    source="tushare",
                ),
                NamechangeLight(
                    row_key_hash="history-000001",
                    ts_code="000001.SZ",
                    name="深发展A",
                    start_date=date(2000, 1, 1),
                    end_date=date(2010, 12, 31),
                    fetched_at=base_time,
                ),
            ]
        )
        news_rows = [
            NewsLight(
                row_key_hash="news-code",
                src="sina",
                news_time=base_time,
                title="000001.SZ 业务公告",
                content="其他频道正文",
                channels="其他",
                source="tushare",
                fetched_at=base_time,
            ),
            NewsLight(
                row_key_hash="news-current-name",
                src="sina",
                news_time=base_time + timedelta(seconds=1),
                title="平安银行发布公告",
                content=None,
                channels="公司",
                source="tushare",
                fetched_at=base_time + timedelta(seconds=1),
            ),
            NewsLight(
                row_key_hash="news-history-name",
                src="sina",
                news_time=datetime(2005, 3, 1, tzinfo=timezone.utc),
                title="深发展A历史公告",
                content=None,
                channels="其他",
                source="tushare",
                fetched_at=base_time + timedelta(seconds=2),
            ),
            NewsLight(
                row_key_hash="news-unmatched",
                src="sina",
                news_time=base_time + timedelta(seconds=3),
                title="没有股票名称",
                content=None,
                channels="公司",
                source="tushare",
                fetched_at=base_time + timedelta(seconds=3),
            ),
        ]
        session.add_all(news_rows)
        session.add(
            NewsStockLink(
                news_id="news-unmatched",
                ts_code="600519.SH",
                match_method="SHORT_NAME_EXACT",
                source_field="title",
                rule_version="old-rule",
            )
        )
        session.commit()


def test_materialize_processes_all_channels_and_cleans_empty_matches() -> None:
    _engine, session_factory = _session_factory()
    base_time = datetime(2026, 5, 29, 8, 0, tzinfo=timezone.utc)
    _seed(session_factory, base_time)

    stats = NewsStockLinkingService(session_factory=session_factory, batch_size=2).materialize(
        window_start=None,
        window_end=base_time + timedelta(hours=1),
    )

    assert stats.rows_fetched == 4
    assert stats.matched_news_count == 3
    assert stats.unmatched_news_count == 1
    assert stats.links_inserted == 3
    assert stats.links_deleted == 1
    assert stats.batch_count == 2

    with session_factory() as session:
        rows = session.execute(
            select(NewsStockLink.news_id, NewsStockLink.ts_code, NewsStockLink.match_method)
            .order_by(NewsStockLink.news_id, NewsStockLink.ts_code)
        ).all()
    assert [(row[0], row[1]) for row in rows] == [
        ("news-code", "000001.SZ"),
        ("news-current-name", "000001.SZ"),
        ("news-history-name", "000001.SZ"),
    ]


def test_overlap_rerun_is_idempotent_and_preserves_created_at() -> None:
    _engine, session_factory = _session_factory()
    base_time = datetime(2026, 5, 29, 8, 0, tzinfo=timezone.utc)
    _seed(session_factory, base_time)
    service = NewsStockLinkingService(session_factory=session_factory, batch_size=10)

    first = service.materialize(window_start=None, window_end=base_time + timedelta(hours=1))
    with session_factory() as session:
        created_at = session.scalar(
            select(NewsStockLink.created_at).where(
                NewsStockLink.news_id == "news-code",
                NewsStockLink.ts_code == "000001.SZ",
            )
        )
    second = service.materialize(
        window_start=base_time - timedelta(hours=1),
        window_end=base_time + timedelta(hours=1),
        overlap_seconds=3600,
    )

    with session_factory() as session:
        count = session.scalar(select(func.count()).select_from(NewsStockLink))
        current_created_at = session.scalar(
            select(NewsStockLink.created_at).where(
                NewsStockLink.news_id == "news-code",
                NewsStockLink.ts_code == "000001.SZ",
            )
        )
    assert first.rows_saved == 3
    assert second.links_updated == 3
    assert count == 3
    assert current_created_at == created_at


def test_late_news_uses_fetched_at_cursor_even_when_news_time_is_old() -> None:
    _engine, session_factory = _session_factory()
    base_time = datetime(2026, 5, 29, 8, 0, tzinfo=timezone.utc)
    _seed(session_factory, base_time)
    with session_factory() as session:
        session.add(
            NewsLight(
                row_key_hash="news-late",
                src="sina",
                news_time=datetime(2020, 1, 1, tzinfo=timezone.utc),
                title="600519.SH 晚到新闻",
                content=None,
                channels="其他",
                source="tushare",
                fetched_at=base_time + timedelta(minutes=30),
            )
        )
        session.commit()

    stats = NewsStockLinkingService(session_factory=session_factory).materialize(
        window_start=base_time + timedelta(minutes=10),
        window_end=base_time + timedelta(hours=1),
    )

    assert stats.rows_fetched == 1
    with session_factory() as session:
        assert session.scalar(
            select(NewsStockLink.ts_code).where(NewsStockLink.news_id == "news-late")
        ) == "600519.SH"


def test_failed_batch_rolls_back_only_current_batch(monkeypatch) -> None:
    _engine, session_factory = _session_factory()
    base_time = datetime(2026, 5, 29, 8, 0, tzinfo=timezone.utc)
    _seed(session_factory, base_time)
    original_upsert = NewsStockLinkDAO.bulk_upsert_current
    calls = 0

    def fail_second_batch(self, rows):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic second batch failure")
        return original_upsert(self, rows)

    monkeypatch.setattr(NewsStockLinkDAO, "bulk_upsert_current", fail_second_batch)
    with pytest.raises(RuntimeError, match="synthetic second batch failure"):
        NewsStockLinkingService(session_factory=session_factory, batch_size=2).materialize(
            window_start=None,
            window_end=base_time + timedelta(hours=1),
        )

    with session_factory() as session:
        keys = set(session.execute(select(NewsStockLink.news_id, NewsStockLink.ts_code)).all())
    assert ("news-code", "000001.SZ") in keys
    assert ("news-current-name", "000001.SZ") in keys
    assert ("news-unmatched", "600519.SH") in keys
    assert ("news-history-name", "000001.SZ") not in keys
