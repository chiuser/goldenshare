from datetime import date, datetime, time
from pathlib import Path
from runpy import run_path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from src.foundation.config.settings import get_settings
from src.foundation.datasets import get_dataset_definition
from src.foundation.ingestion.normalizer import NormalizedBatch
from src.foundation.ingestion.writer import DatasetWriter
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.raw.raw_index_mins import RawIndexMins
from tests.wealth_watchlist_postgres_support import PG_BIN, isolated_postgres


ROOT = Path(__file__).resolve().parents[1]
REVISION_WITH_AUXILIARY_TABLE = "20261126_000192"
RETIREMENT_REVISION = "20261126_000193"


def bar(day, code, vol, *, freq="30min", stamp=time(15)):
    return {
        "ts_code": code,
        "freq": freq,
        "trade_time": datetime.combine(day, stamp),
        "close": 3476.47,
        "vol": vol,
        "amount": 650_000_000_000.0,
    }


def assert_writer_uses_existing_shares(engine):
    # The 9→10 November and 24→25 November verified aggregates are assembled
    # as a short uninterrupted fixture. November 11 supplies a second lot day.
    days = [date(2026, 11, day) for day in (9, 10, 11, 12)]
    sh, sz, boundary = "000001.SH", "399001.SZ", "399006.SZ"
    baseline = [
        bar(days[0], sh, 20_000_000_000, stamp=time(14, 30)),
        bar(days[0], sh, 22_772_225_700),
        bar(days[0], sz, 39_000_000_000),
        bar(days[0], boundary, 45_000_000_000),
        bar(days[0], boundary, 100_000_000_000, freq="5min"),
    ]
    rows = [
        bar(days[2], sh, 493_526_296),
        bar(days[1], sh, 999),
        bar(days[1], sh, 404_865_177),
        bar(days[3], sh, 47_256_142_700),
        bar(days[1], sz, 40_000_000_000),
        bar(days[1], boundary, 900_000_000),
    ]
    batch = NormalizedBatch(unit_id="index-minutes", rows_normalized=rows, rows_rejected=0, rejected_reasons={})
    definition = get_dataset_definition("index_mins")
    with Session(engine) as session:
        session.add_all(TradeCalendar(exchange="SSE", trade_date=day, is_open=True) for day in days)
        session.execute(RawIndexMins.__table__.insert(), baseline)
        session.commit()
        writer = DatasetWriter(session)

        def check():
            reads = []

            def record(conn, cursor, statement, parameters, context, executemany):
                if statement.lower().startswith("select sum(raw_tushare.index_mins.vol)"):
                    reads.append(parameters)

            event.listen(engine, "before_cursor_execute", record)
            try:
                result = writer.write(definition=definition, batch=batch)
            finally:
                event.remove(engine, "before_cursor_execute", record)
            assert len(reads) == 3
            assert result.rows_written == 5
            assert result.rows_rejected == 1
            prices = session.scalars(
                select(RawIndexMins).where(RawIndexMins.trade_time >= datetime.combine(days[1], time.min))
                .order_by(RawIndexMins.ts_code, RawIndexMins.trade_time)
            ).all()
            assert [price.vol for price in prices] == [
                40_486_517_700, 49_352_629_600, 47_256_142_700, 40_000_000_000, 900_000_000
            ]
            assert all(price.amount == 650_000_000_000 and price.close == 3476.47 for price in prices)

        check()
        session.rollback()
        assert len(session.scalars(select(RawIndexMins)).all()) == len(baseline)

        check()
        session.commit()
        check()
        session.commit()
        assert rows[2]["vol"] == 404_865_177


def test_index_minutes_use_existing_shares_without_auxiliary_table():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS raw_tushare")
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS core_serving")
        for model in (TradeCalendar, RawIndexMins):
            model.__table__.create(connection)
    assert_writer_uses_existing_shares(engine)


@pytest.mark.skipif(not (PG_BIN / "initdb").is_file(), reason="requires an existing PostgreSQL test binary")
@pytest.mark.parametrize("auxiliary_has_rows", (False, True))
def test_retire_auxiliary_table_from_deployed_revision(tmp_path, monkeypatch, auxiliary_has_rows):
    with isolated_postgres(tmp_path) as engine:
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                for name in (
                    "20260506_000098_add_index_mins_dataset.py",
                    f"{REVISION_WITH_AUXILIARY_TABLE}_add_index_mins_volume_evidence.py",
                ):
                    run_path(ROOT / "alembic" / "versions" / name)["upgrade"]()
            TradeCalendar.__table__.create(connection)
            if auxiliary_has_rows:
                connection.execute(text("""
                    INSERT INTO raw_tushare.index_mins_volume_evidence
                    VALUES ('000001.SH', '30min', '2026-11-26', 100, 'share')
                """))
        monkeypatch.setenv("GOLDENSHARE_ENV_FILE", str(tmp_path / "no-app-env"))
        monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
        config = Config(str(ROOT / "alembic.ini"))
        get_settings.cache_clear()
        try:
            command.stamp(config, REVISION_WITH_AUXILIARY_TABLE)
            if auxiliary_has_rows:
                with pytest.raises(DBAPIError, match="must be empty before retirement"):
                    command.upgrade(config, RETIREMENT_REVISION)
            else:
                command.upgrade(config, RETIREMENT_REVISION)

            with engine.connect() as connection:
                old_table = connection.scalar(text("SELECT to_regclass('raw_tushare.index_mins_volume_evidence')"))
                head = connection.scalar(text("SELECT version_num FROM alembic_version"))
                assert connection.scalar(text("SELECT to_regclass('raw_tushare.index_mins')"))
                assert connection.scalar(text("SELECT to_regclass('core_serving.index_minute_bar')"))
                if auxiliary_has_rows:
                    assert old_table and head == REVISION_WITH_AUXILIARY_TABLE
                    assert connection.scalar(text("SELECT count(*) FROM raw_tushare.index_mins_volume_evidence")) == 1
                else:
                    assert old_table is None and head == RETIREMENT_REVISION
            if not auxiliary_has_rows:
                assert_writer_uses_existing_shares(engine)
                with engine.connect() as connection:
                    assert connection.scalar(text("SELECT count(*) FROM core_serving.index_minute_bar")) == 10
        finally:
            get_settings.cache_clear()
