from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from src.foundation.dao.news_dao import RawNewsDAO


class DummySession:
    def __init__(self) -> None:
        self.statements = []

    def execute(self, statement):  # type: ignore[no-untyped-def]
        self.statements.append(statement)
        return SimpleNamespace(rowcount=1)


def test_raw_news_bulk_upsert_does_not_update_composite_identity() -> None:
    session = DummySession()
    dao = RawNewsDAO(session)

    dao.bulk_upsert(
        [
            {
                "row_key_hash": "hash-1",
                "src": "sina",
                "news_time": datetime.fromisoformat("2026-04-24T10:11:12+08:00"),
                "title": "快讯标题",
                "content": "快讯正文",
            }
        ],
        conflict_columns=["news_time", "row_key_hash"],
    )

    sql = str(session.statements[0])
    assert "ON CONFLICT (news_time, row_key_hash)" in sql
    assert "news_time = excluded.news_time" not in sql
    assert "row_key_hash = excluded.row_key_hash" not in sql
