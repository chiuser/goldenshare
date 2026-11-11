"""Specified-column SQL contracts; business values are validated by callers."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import Integer, String
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.elements import TextClause

from src.foundation.dao.base_dao import BaseDAO
from src.foundation.models.base import Base
from src.foundation.models.raw.raw_daily_basic import RawDailyBasic


class SingleKeyUpdateRow(Base):
    __tablename__ = "test_update_columns_single_key"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    value: Mapped[str | None] = mapped_column(String(32))


def make_dao(model=RawDailyBasic):
    session = Mock()
    session.get_bind.return_value = SimpleNamespace(dialect=postgresql.dialect())
    session.execute.return_value = SimpleNamespace(rowcount=1)
    dao = BaseDAO(session, model)
    dao.settings = SimpleNamespace(sync_batch_size=1000)
    return dao, session


def test_updates_only_explicit_columns_using_bound_composite_keys():
    dao, session = make_dao()
    day = date(2026, 11, 10)
    assert dao.bulk_update_columns(
        [{"ts_code": "000001.SZ", "trade_date": day, "limit_status": 0, "close": 999}],
        ("limit_status",),
    ) == 1
    statement, params = session.execute.call_args.args
    assert isinstance(statement, TextClause)
    sql = str(statement)
    assert sql.startswith("UPDATE raw_tushare.daily_basic AS target SET limit_status = incoming.limit_status ")
    assert "target.ts_code = incoming.ts_code AND target.trade_date = incoming.trade_date" in sql
    assert "target.limit_status IS DISTINCT FROM incoming.limit_status" in sql
    assert "CAST(:v_0_0 AS VARCHAR(16))" in sql
    assert "CAST(:v_0_1 AS DATE)" in sql
    assert "CAST(:v_0_2 AS INTEGER)" in sql
    assert "000001.SZ" not in sql and "close" not in sql and "updated_at" not in sql
    assert params == {"v_0_0": "000001.SZ", "v_0_1": day, "v_0_2": 0}
    session.commit.assert_not_called()
    session.rollback.assert_not_called()


@pytest.mark.parametrize("columns", [(), ("ts_code",), ("trade_date",), ("missing",)])
def test_rejects_non_model_columns_and_primary_key_updates(columns):
    dao, session = make_dao()
    with pytest.raises(ValueError, match="真实的非主键列"):
        dao.bulk_update_columns([{}], columns)
    session.execute.assert_not_called()


def test_batches_by_selected_parameters_and_preserves_zero_rowcount(monkeypatch):
    dao, session = make_dao()
    # Artificial limit: (8 - 2) / (two keys + one updated column) = two rows.
    monkeypatch.setattr(BaseDAO, "PG_MAX_BIND_PARAMS", 8)
    monkeypatch.setattr(BaseDAO, "PG_BIND_PARAM_RESERVE", 2)
    session.execute.side_effect = [SimpleNamespace(rowcount=n) for n in (2, 0, 1)]
    rows = [
        {"ts_code": f"{i:06d}.SZ", "trade_date": date(2026, 11, 10), "limit_status": i, "close": 999}
        for i in range(5)
    ]
    assert dao.bulk_update_columns(rows, ("limit_status",)) == 3
    assert [len(call.args[1]) for call in session.execute.call_args_list] == [6, 6, 3]
    session.commit.assert_not_called()
    session.rollback.assert_not_called()


def test_reads_primary_key_from_model_instead_of_daily_basic_constants():
    dao, session = make_dao(SingleKeyUpdateRow)
    dao.bulk_update_columns([{"id": 7, "value": "new"}], ("value",))
    statement, params = session.execute.call_args.args
    assert "target.id = incoming.id" in str(statement)
    assert "trade_date" not in str(statement)
    assert params == {"v_0_0": 7, "v_0_1": "new"}


def test_empty_input_does_not_execute_or_commit():
    dao, session = make_dao()
    assert dao.bulk_update_columns([], ("limit_status",)) == 0
    session.execute.assert_not_called()
    session.commit.assert_not_called()
    session.rollback.assert_not_called()
