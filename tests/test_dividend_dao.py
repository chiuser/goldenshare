from __future__ import annotations

from types import SimpleNamespace

from src.dao.dividend_dao import EquityDividendDAO, RawDividendDAO
from src.models.base import Base
from src.models.core.equity_dividend import EquityDividend
from src.models.raw.raw_dividend import RawDividend


class DummySession:
    def __init__(self) -> None:
        self.statements = []

    def execute(self, statement):  # type: ignore[no-untyped-def]
        self.statements.append(statement)
        return SimpleNamespace(rowcount=1)


def test_raw_dividend_bulk_upsert_does_not_update_surrogate_id() -> None:
    session = DummySession()
    dao = RawDividendDAO(session)

    dao.bulk_upsert(
        [
            {
                "row_key_hash": "hash-1",
                "ts_code": "000001.SZ",
                "div_proc": "预案",
            }
        ],
        conflict_columns=["row_key_hash"],
    )

    sql = str(session.statements[0])
    assert "id = excluded.id" not in sql


def test_core_dividend_bulk_upsert_does_not_update_surrogate_id() -> None:
    session = DummySession()
    dao = EquityDividendDAO(session)

    dao.bulk_upsert(
        [
            {
                "row_key_hash": "hash-1",
                "event_key_hash": "event-1",
                "ts_code": "000001.SZ",
                "end_date": "2025-12-31",
                "ann_date": "2026-03-21",
                "div_proc": "预案",
            }
        ],
        conflict_columns=["row_key_hash"],
    )

    sql = str(session.statements[0])
    assert "id = excluded.id" not in sql
