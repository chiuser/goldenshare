from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.dao.base_dao import BaseDAO
from src.foundation.models.base import Base


class DummyRow(Base):
    __tablename__ = "dummy_row"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    value: Mapped[str | None] = mapped_column(String(32))


class DummySession:
    def __init__(self) -> None:
        self.statements = []

    def execute(self, statement):  # type: ignore[no-untyped-def]
        self.statements.append(statement)
        return SimpleNamespace(rowcount=1)


def test_bulk_upsert_keeps_last_duplicate_row() -> None:
    session = DummySession()
    dao = BaseDAO(session, DummyRow)

    dao.bulk_upsert(
        [
            {"id": 1, "value": "first"},
            {"id": 1, "value": "second"},
        ]
    )

    params = session.statements[0].compile().params
    assert params["value_m0"] == "second"


def test_bulk_upsert_raises_when_conflict_key_missing() -> None:
    session = DummySession()
    dao = BaseDAO(session, DummyRow)

    with pytest.raises(ValueError, match="missing conflict key fields: id"):
        dao.bulk_upsert([{"value": "missing-id"}])
