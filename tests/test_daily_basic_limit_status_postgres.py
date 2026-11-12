"""Actual PostgreSQL normalizer/writer transactions and query-error isolation.

SOURCE_ROW is the public 19-column MCP observation recorded in the unit fixture.
The modified dates/values and the temporary CHECK are deliberate failure inputs.
"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import Column, MetaData, String, Table, select, text
from sqlalchemy.orm import Session

from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion.errors import IngestionError, IngestionNormalizeError
from src.foundation.ingestion.executor import IngestionExecutor
from src.foundation.models.core_serving.equity_daily_basic import EquityDailyBasic
from src.foundation.models.core_serving.security_serving import Security
from src.foundation.models.raw.raw_daily_basic import RawDailyBasic
from src.ops.runtime.task_run_dispatcher import TaskRunDispatcher
from tests.test_daily_basic_limit_status import (
    DAY,
    ERROR_CODE,
    SOURCE_ROW,
    Source,
    make_executor,
    request,
    unit,
)
from tests.wealth_watchlist_postgres_support import isolated_postgres


def create_tables(engine):
    with engine.begin() as connection:
        connection.execute(text("CREATE SCHEMA raw_tushare"))
        connection.execute(text("CREATE SCHEMA core_serving"))
        for model in (RawDailyBasic, EquityDailyBasic, Security):
            model.__table__.create(connection)
        connection.execute(Security.__table__.insert().values(
            ts_code="000001.SZ", name="平安银行", security_type="EQUITY", list_status="L"))


def test_real_two_table_pipeline_retains_the_previous_date_and_rolls_back_writer_failure(tmp_path):
    with isolated_postgres(tmp_path) as engine:
        create_tables(engine)
        next_day, last_day = date(2026, 11, 11), date(2026, 11, 12)
        source = Source({DAY: [SOURCE_ROW], next_day: [
            {**SOURCE_ROW, "trade_date": "20261111", "ts_code": "000002.SZ"},
            {**SOURCE_ROW, "trade_date": "20261111", "limit_status": 1.5},
        ], last_day: [SOURCE_ROW]})
        with Session(engine) as session:
            executor = IngestionExecutor(session)
            executor.source_client = source
            with pytest.raises(IngestionNormalizeError) as caught:
                executor.run(request=request(), definition=get_dataset_definition("daily_basic"),
                             units=(unit(), unit(next_day), unit(last_day)))
            assert caught.value.structured_error.error_code == ERROR_CODE
            assert caught.value.structured_error.details["committed_progress"]["rows_committed"] == 1
        assert source.called == [DAY, next_day]
        with Session(engine) as session:
            for model in (RawDailyBasic, EquityDailyBasic):
                rows = session.scalars(select(model)).all()
                assert len(rows) == 1 and rows[0].trade_date == DAY
                # Literal gold values are independent of the conversion implementation.
                row = rows[0]
                assert (row.ts_code, row.close, row.turnover_rate, row.pe, row.circ_mv, row.limit_status) == (
                    "000001.SZ", Decimal("11.8600"), Decimal("0.3859"), Decimal("5.3985"), Decimal("23015142.4100"), 4)

        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE core_serving.equity_daily_basic ADD CONSTRAINT stage2_writer_failure CHECK (trade_date <> '2026-11-11'::date OR limit_status <> 4)"))
        with Session(engine) as session:
            executor = IngestionExecutor(session)
            executor.source_client = Source({DAY: [SOURCE_ROW], next_day: [
                {**SOURCE_ROW, "trade_date": "20261111"},
            ]})
            with pytest.raises(IngestionError) as caught:
                executor.run(request=request(), definition=get_dataset_definition("daily_basic"), units=(unit(), unit(next_day)))
            assert caught.value.structured_error.error_code != ERROR_CODE
        with Session(engine) as session:
            for model in (RawDailyBasic, EquityDailyBasic):
                rows = session.scalars(select(model)).all()
                assert len(rows) == 1 and rows[0].trade_date == DAY and rows[0].limit_status == 4


def test_real_postgres_name_query_failure_keeps_the_outer_session_usable(tmp_path, monkeypatch):
    from src.ops.runtime import task_run_dispatcher as module

    executor, _, _ = make_executor({DAY: [{**SOURCE_ROW, "limit_status": 1.5}]})
    with pytest.raises(IngestionNormalizeError) as caught:
        executor.run(request=request(), definition=get_dataset_definition("daily_basic"), units=(unit(),))
    with isolated_postgres(tmp_path) as engine:
        create_tables(engine)
        with Session(engine) as session:
            assert "平安银行" in TaskRunDispatcher._source_validation_error_message(session, caught.value)
            session.rollback()  # Production exception branches also call the helper after rollback.
            absent = Table("missing_name_fixture", MetaData(), Column("ts_code", String), Column("name", String), schema="core_serving")
            monkeypatch.setattr(module, "Security", SimpleNamespace(ts_code=absent.c.ts_code, name=absent.c.name))
            message = TaskRunDispatcher._source_validation_error_message(session, caught.value)
            assert "名称未找到" in message and "1.5" in message and "float" in message
            assert session.scalar(text("SELECT 1")) == 1
            assert caught.value.structured_error.error_code == ERROR_CODE
