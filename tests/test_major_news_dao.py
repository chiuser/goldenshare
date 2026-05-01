from __future__ import annotations

from types import SimpleNamespace

from src.foundation.dao.major_news_dao import RawMajorNewsDAO


class DummySession:
    def __init__(self) -> None:
        self.statements = []

    def execute(self, statement):  # type: ignore[no-untyped-def]
        self.statements.append(statement)
        return SimpleNamespace(rowcount=1)


def test_raw_major_news_bulk_upsert_does_not_update_surrogate_id() -> None:
    session = DummySession()
    dao = RawMajorNewsDAO(session)

    dao.bulk_upsert(
        [
            {
                "row_key_hash": "hash-1",
                "src": "新浪财经",
                "pub_time": "2026-04-24 10:11:12+08:00",
                "title": "新闻标题",
                "content": "新闻内容",
            }
        ],
        conflict_columns=["row_key_hash"],
    )

    sql = str(session.statements[0])
    assert "id = excluded.id" not in sql
