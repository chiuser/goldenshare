from __future__ import annotations

from types import SimpleNamespace

from src.foundation.dao.cctv_news_dao import RawCctvNewsDAO


class DummySession:
    def __init__(self) -> None:
        self.statements = []

    def execute(self, statement):  # type: ignore[no-untyped-def]
        self.statements.append(statement)
        return SimpleNamespace(rowcount=1)


def test_raw_cctv_news_bulk_upsert_does_not_update_surrogate_id() -> None:
    session = DummySession()
    dao = RawCctvNewsDAO(session)

    dao.bulk_upsert(
        [
            {
                "row_key_hash": "hash-1",
                "date": "2026-04-24",
                "title": "新闻标题",
                "content": "新闻内容",
            }
        ],
        conflict_columns=["row_key_hash"],
    )

    sql = str(session.statements[0])
    assert "id = excluded.id" not in sql
