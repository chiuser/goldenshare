from __future__ import annotations

from datetime import date

from src.biz.queries.wealth.news_intelligence.source_query import (
    NewsIntelligenceReplaySourceQuery,
    ensure_repeatable_read_only_transaction,
)
from src.biz.services.wealth.news_intelligence.replay import build_replay_windows


class _Dialect:
    def __init__(self, name: str) -> None:
        self.name = name


class _Bind:
    def __init__(self, dialect_name: str) -> None:
        self.dialect = _Dialect(dialect_name)


class _EmptySession:
    def __init__(self, dialect_name: str = "sqlite") -> None:
        self.bind = _Bind(dialect_name)
        self.info = {}
        self.statements = []
        self.transaction = None

    def get_bind(self):
        return self.bind

    def get_transaction(self):
        return self.transaction

    def execute(self, statement):
        self.statements.append(statement)
        if self.bind.dialect.name == "postgresql" and self.transaction is None:
            self.transaction = object()
        return ()


def test_timed_source_query_selects_required_fields_without_legacy_score() -> None:
    session = _EmptySession()
    query = NewsIntelligenceReplaySourceQuery()
    assert (
        list(
            query.stream_timed_window(
                session, window=build_replay_windows(date(2026, 9, 20))[0]
            )
        )
        == []
    )
    assert len(session.statements) == 2
    sql = "\n".join(str(statement) for statement in session.statements)
    assert "core_serving_light.news.score" not in sql
    assert "core_serving_light.news.news_time" in sql
    assert "core_serving_light.major_news.pub_time" in sql


def test_cctv_source_query_uses_date_without_intraday_field() -> None:
    session = _EmptySession()
    query = NewsIntelligenceReplaySourceQuery()
    assert list(query.stream_cctv_date(session, content_date=date(2026, 9, 20))) == []
    sql = str(session.statements[0])
    assert "core_serving_light.cctv_news.date" in sql
    assert "published_at" not in sql


def test_postgresql_read_only_snapshot_is_set_once_per_transaction() -> None:
    session = _EmptySession("postgresql")
    ensure_repeatable_read_only_transaction(session)
    ensure_repeatable_read_only_transaction(session)
    assert len(session.statements) == 1
    assert (
        str(session.statements[0])
        == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
    )
