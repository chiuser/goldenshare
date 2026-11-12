"""Storage-only acceptance, using a new temporary PostgreSQL cluster.

The legacy DDL follows RawDailyBasic/EquityDailyBasic before this change, as
recorded in LLD sections 2 and 4. It is deliberately independent of the new ORM
and migration. No network source, existing database URL or production data.
"""

from datetime import date
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import Integer, event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.foundation.dao.equity_daily_basic_dao import EquityDailyBasicDAO
from src.foundation.dao.generic import GenericDAO
from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.models.core_serving.equity_daily_basic import EquityDailyBasic
from src.foundation.models.raw.raw_daily_basic import RawDailyBasic
from tests.wealth_watchlist_postgres_support import isolated_postgres

ROOT = Path(__file__).resolve().parents[1]
REVISION = "20261112_000188"
DAY = date(2026, 11, 10)
TABLES = ("raw_tushare.daily_basic", "core_serving.equity_daily_basic")
LEGACY_FIELDS = (
    "ts_code", "trade_date", "close", "turnover_rate", "turnover_rate_f",
    "volume_ratio", "pe", "pe_ttm", "pb", "ps", "ps_ttm", "dv_ratio",
    "dv_ttm", "total_share", "float_share", "free_share", "total_mv", "circ_mv",
)
LEGACY_BUSINESS_DDL = """
    ts_code VARCHAR(16) NOT NULL, trade_date DATE NOT NULL,
    close NUMERIC(18,4), turnover_rate NUMERIC(12,4),
    turnover_rate_f NUMERIC(12,4), volume_ratio NUMERIC(12,4),
    pe NUMERIC(18,4), pe_ttm NUMERIC(18,4), pb NUMERIC(18,4),
    ps NUMERIC(18,4), ps_ttm NUMERIC(18,4), dv_ratio NUMERIC(12,4),
    dv_ttm NUMERIC(12,4), total_share NUMERIC(20,4), float_share NUMERIC(20,4),
    free_share NUMERIC(20,4), total_mv NUMERIC(20,4), circ_mv NUMERIC(20,4),
    PRIMARY KEY (ts_code, trade_date)
"""


def migration():
    return ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini"))).get_revision(REVISION).module


def column_schema(connection, table):
    schema, name = table.split(".")
    return [
        {**column, "type": column["type"].compile(dialect=connection.dialect)}
        for column in inspect(connection).get_columns(name, schema=schema)
    ]


def legacy_rows(connection, table):
    return [
        {key: value for key, value in row.items() if key != "limit_status"}
        for row in connection.execute(text(f"SELECT * FROM {table} ORDER BY ts_code, trade_date")).mappings()
    ]


def status_rows(connection, table):
    return connection.execute(text(
        f"SELECT ts_code, trade_date, limit_status FROM {table} ORDER BY ts_code, trade_date"
    )).all()


def create_legacy_fixture(connection):
    connection.execute(text("CREATE SCHEMA raw_tushare"))
    connection.execute(text("CREATE SCHEMA core_serving"))
    connection.execute(text(f"""CREATE TABLE {TABLES[0]} (
        {LEGACY_BUSINESS_DDL}, api_name VARCHAR(32) NOT NULL DEFAULT 'daily_basic',
        fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(), raw_payload TEXT)"""))
    connection.execute(text(f"""CREATE TABLE {TABLES[1]} (
        {LEGACY_BUSINESS_DDL}, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"""))
    for name, columns in (
        ("idx_equity_daily_basic_trade_date", "trade_date"),
        ("idx_equity_daily_basic_pb_trade_date", "trade_date, pb"),
        ("idx_equity_daily_basic_total_mv_trade_date", "trade_date, total_mv"),
    ):
        connection.execute(text(f"CREATE INDEX {name} ON {TABLES[1]} ({columns})"))
    for table in TABLES:
        system_columns, system_values = (
            ("api_name,fetched_at,raw_payload", "'daily_basic','2020-01-02T03:04:05Z','legacy payload'")
            if table == TABLES[0] else
            ("created_at,updated_at", "'2020-01-01T00:00:00Z','2020-01-02T03:04:05Z'")
        )
        for code, day in (("000001.SZ", DAY), ("000001.SZ", date(2026, 11, 11)), ("000002.SZ", DAY)):
            connection.execute(text(f"""INSERT INTO {table}
                (ts_code,trade_date,close,turnover_rate,pe,total_share,{system_columns})
                VALUES (:code,:day,10.1234,NULL,-2.5000,12345.6789,{system_values})"""),
                {"code": code, "day": day})


@pytest.mark.parametrize("model", [RawDailyBasic, EquityDailyBasic])
def test_models_add_only_nullable_integer_status(model):
    column = model.__table__.c.limit_status
    assert isinstance(column.type, Integer)
    assert column.nullable and not column.primary_key
    assert column.default is None and column.server_default is None
    assert tuple(c.name for c in model.__table__.primary_key) == ("ts_code", "trade_date")
    assert get_dataset_definition("daily_basic").source.source_fields == (*LEGACY_FIELDS, "limit_status")


def test_migration_attaches_to_verified_head():
    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert script.get_revision(REVISION).down_revision == "20261031_000187"
    assert script.get_heads() == [REVISION]


def test_real_postgres_migration_updates_and_transaction_ownership(tmp_path):
    # Reuse only the existing empty-cluster helper, never its watchlist seed.
    with isolated_postgres(tmp_path) as engine:
        before, old_columns, old_indexes, old_keys = {}, {}, {}, {}
        with engine.begin() as connection:
            create_legacy_fixture(connection)
            for table in TABLES:
                schema, name = table.split(".")
                inspector = inspect(connection)
                old_columns[table] = column_schema(connection, table)
                assert tuple(c["name"] for c in old_columns[table][:18]) == LEGACY_FIELDS
                assert all(c["name"] != "limit_status" for c in old_columns[table])
                old_indexes[table] = inspector.get_indexes(name, schema=schema)
                old_keys[table] = inspector.get_pk_constraint(name, schema=schema)
                before[table] = legacy_rows(connection, table)
            with Operations.context(MigrationContext.configure(connection)):
                migration().upgrade()
            for table in TABLES:
                schema, name = table.split(".")
                inspector = inspect(connection)
                new_columns = inspector.get_columns(name, schema=schema)
                assert column_schema(connection, table)[:-1] == old_columns[table]
                added = new_columns[-1]
                assert added["name"] == "limit_status" and isinstance(added["type"], Integer)
                assert added["nullable"] and added["default"] is None
                assert inspector.get_indexes(name, schema=schema) == old_indexes[table]
                assert inspector.get_pk_constraint(name, schema=schema) == old_keys[table]
                assert all(row[2] is None for row in status_rows(connection, table))
                assert legacy_rows(connection, table) == before[table]

        emitted = []

        @event.listens_for(engine, "before_cursor_execute")
        def capture_update(connection, cursor, statement, parameters, context, executemany):
            if statement.startswith("UPDATE "):
                emitted.append((statement, parameters))

        values = [
            {"ts_code": "000001.SZ", "trade_date": DAY, "limit_status": 0, "close": 999},
            {"ts_code": "000002.SZ", "trade_date": DAY, "limit_status": 6, "close": 999},
            {"ts_code": "999999.SZ", "trade_date": DAY, "limit_status": 1, "close": 999},
        ]
        expected = [("000001.SZ", DAY, 0), ("000001.SZ", date(2026, 11, 11), None), ("000002.SZ", DAY, 6)]

        with Session(engine) as session:
            assert GenericDAO(session, RawDailyBasic).bulk_update_columns(values, ("limit_status",)) == 2
            assert EquityDailyBasicDAO(session).bulk_update_columns(values, ("limit_status",)) == 2
            for table in TABLES:
                assert status_rows(session, table) == expected
            session.rollback()
        with engine.connect() as connection:
            for table in TABLES:
                assert all(row[2] is None for row in status_rows(connection, table))

        with Session(engine) as session:
            assert GenericDAO(session, RawDailyBasic).bulk_update_columns(values, ("limit_status",)) == 2
            assert EquityDailyBasicDAO(session).bulk_update_columns(values, ("limit_status",)) == 2
            session.commit()
        with engine.connect() as connection:
            for table in TABLES:
                assert status_rows(connection, table) == expected
                assert legacy_rows(connection, table) == before[table]

        with Session(engine) as session:
            raw = GenericDAO(session, RawDailyBasic)
            assert raw.bulk_update_columns(values, ("limit_status",)) == 0
            assert EquityDailyBasicDAO(session).bulk_update_columns(values, ("limit_status",)) == 0
            # A nullable-column operation is a DAO type test, not a permitted source NULL.
            null_status = [{"ts_code": "000001.SZ", "trade_date": DAY, "limit_status": None}]
            assert raw.bulk_update_columns(null_status, ("limit_status",)) == 1
            assert raw.bulk_update_columns(null_status, ("limit_status",)) == 0
            session.rollback()

        # Deliberate database failure on the second table; not a production rule.
        with engine.begin() as connection:
            connection.execute(text(f"ALTER TABLE {TABLES[1]} ADD CONSTRAINT test_reject_five CHECK (limit_status IS DISTINCT FROM 5)"))
        with Session(engine) as session:
            change = [{"ts_code": "000001.SZ", "trade_date": DAY, "limit_status": 5}]
            assert GenericDAO(session, RawDailyBasic).bulk_update_columns(change, ("limit_status",)) == 1
            with pytest.raises(IntegrityError):
                EquityDailyBasicDAO(session).bulk_update_columns(change, ("limit_status",))
            session.rollback()
        with engine.connect() as connection:
            for table in TABLES:
                assert status_rows(connection, table) == expected
                assert legacy_rows(connection, table) == before[table]
        assert emitted
        for sql, parameters in emitted:
            assert sql.split(" SET ", 1)[1].split(" FROM ", 1)[0] == "limit_status = incoming.limit_status"
            assert "updated_at" not in sql and "000001.SZ" not in sql
            assert parameters

        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                migration().downgrade()
            for table in TABLES:
                schema, name = table.split(".")
                inspector = inspect(connection)
                assert column_schema(connection, table) == old_columns[table]
                assert inspector.get_indexes(name, schema=schema) == old_indexes[table]
                assert inspector.get_pk_constraint(name, schema=schema) == old_keys[table]
                assert legacy_rows(connection, table) == before[table]
            with Operations.context(MigrationContext.configure(connection)):
                migration().upgrade()
            assert all(row[2] is None for table in TABLES for row in status_rows(connection, table))
