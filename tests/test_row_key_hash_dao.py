from __future__ import annotations

from types import SimpleNamespace

from src.foundation.dao.row_key_hash_dao import RowKeyHashDAO
from src.foundation.models.raw.raw_anns_d import RawAnnsD


class DummySession:
    def __init__(self) -> None:
        self.statements = []

    def execute(self, statement):  # type: ignore[no-untyped-def]
        self.statements.append(statement)
        return SimpleNamespace(rowcount=1)


def test_row_key_hash_dao_does_not_update_surrogate_id() -> None:
    session = DummySession()
    dao = RowKeyHashDAO(session, RawAnnsD)

    dao.bulk_upsert(
        [
            {
                "row_key_hash": "hash-1",
                "ann_date": "2026-05-14",
                "ts_code": "600000.SH",
                "title": "公告标题",
                "url": "https://example.test/a.pdf",
                "rec_time": "2026-05-14 08:30:01+08:00",
            }
        ],
        conflict_columns=["row_key_hash"],
    )

    sql = str(session.statements[0])
    assert "id = excluded.id" not in sql
