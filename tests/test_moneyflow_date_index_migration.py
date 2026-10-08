from __future__ import annotations

import importlib.util
from datetime import date
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.dialects import postgresql

from src.foundation.dao.generic import GenericDAO
from src.foundation.models.raw.raw_moneyflow import RawMoneyflow


def _migration():
    path = Path(__file__).parents[1] / "alembic/versions/20261008_000184_add_moneyflow_date_index.py"
    spec = importlib.util.spec_from_file_location("moneyflow_date_index_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_concurrent_index_render_has_transaction_boundary_and_strict_resume_checks(monkeypatch):
    migration = _migration()
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    monkeypatch.setattr(migration, "op", Operations(context))
    with context.begin_transaction():
        migration.upgrade()
    sql = output.getvalue()
    create = sql.index("CREATE INDEX CONCURRENTLY IF NOT EXISTS")
    assert sql.index("COMMIT;") < create < sql.rindex("BEGIN;")
    assert "ON raw_tushare.moneyflow (trade_date, ts_code)" in sql
    assert sql.count("pg_get_indexdef(i.indexrelid)") == 2
    assert sql.count("i.indisvalid AND i.indisready AND i.indislive") == 2
    assert "NOT i.indisunique AND NOT i.indisprimary" in sql
    assert "RAISE EXCEPTION 'moneyflow date index missing'" in sql
    assert "invalid or mismatched; stop for inspection" in sql
    assert "SET statement_timeout = '15min'" in sql
    assert "SET lock_timeout = '15s'" in sql
    assert "RESET statement_timeout" in sql and "RESET lock_timeout" in sql
    assert "DROP " not in sql and "ALTER TABLE" not in sql
    assert "INSERT " not in sql and "UPDATE " not in sql and "DELETE " not in sql


def test_index_is_nonunique_and_does_not_change_primary_key_or_upsert(monkeypatch):
    table = RawMoneyflow.__table__
    assert [c.name for c in table.primary_key] == ["ts_code", "trade_date"]
    index = next(i for i in table.indexes if i.name == "idx_raw_tushare_moneyflow_trade_date_ts_code")
    assert [c.name for c in index.columns] == ["trade_date", "ts_code"]
    assert not index.unique
    statements = []
    session = SimpleNamespace(execute=lambda s: (statements.append(s) or SimpleNamespace(rowcount=1)))
    monkeypatch.setattr(
        "src.foundation.dao.base_dao.get_settings", lambda: SimpleNamespace(sync_batch_size=100)
    )
    dao = GenericDAO(session, RawMoneyflow)
    assert dao.bulk_upsert([{"ts_code": "000001.SZ", "trade_date": date(2026, 9, 30), "net_mf_amount": -1}]) == 1
    sql = str(statements[0].compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (ts_code, trade_date) DO UPDATE" in sql


def test_downgrade_cannot_automatically_drop_approved_index():
    with pytest.raises(RuntimeError, match="separate reviewed operation"):
        _migration().downgrade()
