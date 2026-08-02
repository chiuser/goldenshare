from __future__ import annotations

from types import SimpleNamespace

from src.foundation.dao.news_dao import RawNewsDAO


class DummySession:
    def __init__(self) -> None:
        self.statements = []

    def execute(self, statement):  # type: ignore[no-untyped-def]
        self.statements.append(statement)
        return SimpleNamespace(rowcount=1)


def test_raw_news_bulk_upsert_does_not_update_surrogate_id() -> None:
    session = DummySession()
    dao = RawNewsDAO(session)

    dao.bulk_upsert(
        [
            {
                "row_key_hash": "hash-1",
                "src": "sina",
                "news_time": "2026-04-24 10:11:12+08:00",
                "title": "快讯标题",
                "content": "快讯正文",
            }
        ],
        conflict_columns=["row_key_hash"],
    )

    sql = str(session.statements[0])
    assert "id = excluded.id" not in sql
