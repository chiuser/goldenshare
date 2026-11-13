"""Stage-three isolated PostgreSQL acceptance.

SOURCE_ROW is the complete public MCP observation, rechecked on 2026-11-12.
Other codes, dates, old values, budgets and failures below are synthetic inputs.
No existing database or source endpoint is used by this module.
"""

from datetime import date, datetime, timezone
from unittest.mock import Mock

import pytest
from sqlalchemy import event, insert, select, text
from sqlalchemy.orm import Session, sessionmaker

from src.foundation.config.settings import get_settings
from src.foundation.ingestion.daily_basic_limit_status import DailyBasicLimitStatusService
from src.foundation.ingestion.errors import IngestionError
from src.foundation.ingestion.run_errors import IngestionCanceledError
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.equity_daily_basic import EquityDailyBasic
from src.foundation.models.core_serving.security_serving import Security
from src.foundation.models.raw.raw_daily_basic import RawDailyBasic
from src.ops.models.ops.task_run import TaskRun
from src.ops.models.ops.task_run_issue import TaskRunIssue
from src.ops.models.ops.task_run_node import TaskRunNode
from tests.test_daily_basic_limit_status import DAY, SOURCE_ROW
from tests.wealth_watchlist_postgres_support import isolated_postgres

NEXT_DAY = date(2026, 11, 11)
OLD_TIME = datetime(2020, 1, 1, tzinfo=timezone.utc)
CONFIG = {"sync_batch_size": 2, "source_timeout_seconds": 30, "statement_timeout_seconds": 20,
          "observation_timeout_seconds": 2, "progress_interval_seconds": 5}
# Projection observed in the real three-field source requests recorded in LLD §2.3.
DOWNLOAD_FIELDS = ("ts_code", "trade_date", "limit_status")
# Real missing target and list_date from the bounded Prod/source audit in LLD §22/§23.
PRE_LISTING_DAY = date(2018, 12, 24)
PRE_LISTING_CODE = "920964.BJ"
PRE_LISTING_DATE = date(2020, 7, 27)
# The other stock's status is a synthetic valid zero, not an observed historical value.
PRE_LISTING_SOURCE_ROW = {"ts_code": "000001.SZ", "trade_date": "20181224", "limit_status": 0}


def source_rows(day=DAY):
    row = {field: SOURCE_ROW[field] for field in DOWNLOAD_FIELDS}
    return [{**row, "trade_date": day.strftime("%Y%m%d")},
            {**row, "trade_date": day.strftime("%Y%m%d"), "ts_code": "000002.SZ", "limit_status": 0}]


def payload(day=DAY, **overrides):
    return {"trade_date": str(day), "raw_count": 2, "serving_count": 2,
            "request_params": {"trade_date": day.strftime("%Y%m%d")}, "page_limit": 6000, **overrides}


@pytest.fixture
def database(tmp_path):
    with isolated_postgres(tmp_path) as engine:
        with engine.begin() as connection:
            for schema in ("core", "core_serving", "raw_tushare", "ops"):
                connection.execute(text(f"CREATE SCHEMA {schema}"))
            for model in (TradeCalendar, RawDailyBasic, EquityDailyBasic, Security, TaskRun, TaskRunNode, TaskRunIssue):
                model.__table__.create(connection)
            connection.execute(insert(TradeCalendar), [{"exchange": "SSE", "trade_date": day, "is_open": True}
                                                       for day in (DAY, NEXT_DAY)])
            connection.execute(insert(Security), {"ts_code": "000001.SZ", "name": "平安银行", "security_type": "EQUITY", "list_status": "L"})
            for day in (DAY, NEXT_DAY):
                rows = [{**row, "trade_date": day, "limit_status": None, "pe": -17, "close": None}
                        for row in source_rows(day)]
                connection.execute(insert(RawDailyBasic), [{**row, "fetched_at": OLD_TIME, "raw_payload": "old payload"} for row in rows])
                connection.execute(insert(EquityDailyBasic), [{**row, "created_at": OLD_TIME, "updated_at": OLD_TIME} for row in rows])
        yield engine, sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def before_listing_database(database):
    engine, factory = database
    with engine.begin() as connection:
        connection.execute(insert(Security), {"ts_code": PRE_LISTING_CODE, "name": "润农节水",
            "security_type": "EQUITY", "list_status": "L", "list_date": PRE_LISTING_DATE})
        rows = [{"ts_code": code, "trade_date": PRE_LISTING_DAY, "limit_status": None,
                 "pe": -17, "close": None} for code in ("000001.SZ", PRE_LISTING_CODE)]
        connection.execute(insert(RawDailyBasic), [{**row, "fetched_at": OLD_TIME,
            "raw_payload": "old payload"} for row in rows])
        connection.execute(insert(EquityDailyBasic), [{**row, "created_at": OLD_TIME,
            "updated_at": OLD_TIME} for row in rows])
    return engine, factory


def service(factory, rows=None):
    connector = Mock()
    connector.call_bounded.return_value = source_rows() if rows is None else rows
    return DailyBasicLimitStatusService(session_factory=factory, connector=connector)


def execute(value, day=DAY, **kwargs):
    return value.execute_day(payload(day), config=CONFIG, check=kwargs.get("check", lambda: None),
                             observe=kwargs.get("observe", lambda *a, **k: None))


def read_rows(engine):
    with Session(engine) as session:
        return [list(session.execute(select(*model.__table__.c).order_by(model.trade_date, model.ts_code)).mappings())
                for model in (RawDailyBasic, EquityDailyBasic)]


def test_real_pre_listing_missing_target_stays_null_and_other_target_commits(before_listing_database):
    engine, factory = before_listing_database
    before = read_rows(engine)
    value = service(factory, [dict(PRE_LISTING_SOURCE_ROW)])
    result = execute(value, PRE_LISTING_DAY)
    assert result == {"rows_fetched": 1, "rows_saved": 2, "raw_changed": 1, "serving_changed": 1,
                      "already_complete": False, "source_extra_codes": [],
                      "null_before_listing_codes": ["920964.BJ"]}
    after = read_rows(engine)
    for original, persisted in zip(before, after, strict=True):
        assert [{key: val for key, val in row.items() if key != "limit_status"} for row in original] == [
            {key: val for key, val in row.items() if key != "limit_status"} for row in persisted]
        assert {(row["ts_code"], row["limit_status"]) for row in persisted
                if row["trade_date"] == PRE_LISTING_DAY} == {("000001.SZ", 0), ("920964.BJ", None)}


@pytest.mark.parametrize("listing_date", [
    pytest.param(PRE_LISTING_DAY, id="on-listing-date"),
    pytest.param(date(2018, 12, 21), id="after-listing-date"),
    pytest.param(None, id="unknown-listing-date"),
])
def test_missing_target_without_later_listing_date_still_fails(before_listing_database, listing_date):
    engine, factory = before_listing_database
    with engine.begin() as connection:
        connection.execute(text("UPDATE core_serving.security_serving SET list_date=:day WHERE ts_code=:code"),
                           {"day": listing_date, "code": PRE_LISTING_CODE})
    before = read_rows(engine)
    with pytest.raises(IngestionError) as caught:
        execute(service(factory, [dict(PRE_LISTING_SOURCE_ROW)]), PRE_LISTING_DAY)
    assert caught.value.structured_error.error_code == "daily_basic_limit_status.target_mismatch"
    assert caught.value.structured_error.details["missing_codes"] == ["920964.BJ"]
    assert read_rows(engine) == before


def test_missing_stock_basic_record_cannot_justify_leaving_null(before_listing_database):
    engine, factory = before_listing_database
    with engine.begin() as connection:
        # Intentionally remove this key from the isolated stock-basic fixture,
        # without deleting any stock or daily-basic row.
        connection.execute(text("UPDATE core_serving.security_serving SET ts_code='999999.SZ' WHERE ts_code=:code"),
                           {"code": PRE_LISTING_CODE})
    before = read_rows(engine)
    with pytest.raises(IngestionError) as caught:
        execute(service(factory, [dict(PRE_LISTING_SOURCE_ROW)]), PRE_LISTING_DAY)
    assert caught.value.structured_error.details["missing_codes"] == ["920964.BJ"]
    assert read_rows(engine) == before


@pytest.mark.parametrize("raw_status,serving_status", [(4, None), (None, 4), (4, 4), (0, 0)])
def test_pre_listing_exception_never_clears_an_existing_status(before_listing_database, raw_status, serving_status):
    engine, factory = before_listing_database
    with engine.begin() as connection:
        for table, status in (("raw_tushare.daily_basic", raw_status), ("core_serving.equity_daily_basic", serving_status)):
            connection.execute(text(f"UPDATE {table} SET limit_status=:status WHERE trade_date=:day AND ts_code=:code"),
                               {"status": status, "day": PRE_LISTING_DAY, "code": PRE_LISTING_CODE})
    before = read_rows(engine)
    with pytest.raises(IngestionError) as caught:
        execute(service(factory, [dict(PRE_LISTING_SOURCE_ROW)]), PRE_LISTING_DAY)
    assert caught.value.structured_error.details["missing_codes"] == ["920964.BJ"]
    assert read_rows(engine) == before


def test_pre_listing_source_row_with_null_status_is_still_invalid(before_listing_database):
    engine, factory = before_listing_database
    before = read_rows(engine)
    rows = [dict(PRE_LISTING_SOURCE_ROW), {**PRE_LISTING_SOURCE_ROW,
            "ts_code": PRE_LISTING_CODE, "limit_status": None}]
    with pytest.raises(IngestionError) as caught:
        execute(service(factory, rows), PRE_LISTING_DAY)
    assert caught.value.structured_error.details["rejected_reasons"] == {
        "normalize.daily_basic_limit_status_invalid:limit_status": 1}
    assert read_rows(engine) == before


def test_pre_listing_source_with_valid_zero_is_updated_without_listing_query(before_listing_database):
    engine, factory = before_listing_database
    statements = []
    event.listen(engine, "before_cursor_execute", lambda c, u, sql, p, ctx, many: statements.append(sql))
    rows = [dict(PRE_LISTING_SOURCE_ROW), {**PRE_LISTING_SOURCE_ROW, "ts_code": PRE_LISTING_CODE}]
    result = execute(service(factory, rows), PRE_LISTING_DAY)
    assert (result["rows_fetched"], result["rows_saved"], result["raw_changed"], result["serving_changed"]) == (2, 2, 2, 2)
    assert "null_before_listing_codes" not in result
    assert not any("security_serving" in sql for sql in statements)
    assert all(row["limit_status"] == 0 for values in read_rows(engine) for row in values
               if row["trade_date"] == PRE_LISTING_DAY)


def test_pre_listing_replay_rechecks_source_and_fills_status_if_source_recovers(before_listing_database):
    engine, factory = before_listing_database
    listing_queries = []
    event.listen(engine, "before_cursor_execute", lambda c, u, sql, p, ctx, many:
                 listing_queries.append((sql, p)) if "security_serving" in sql else None)
    value = service(factory, [dict(PRE_LISTING_SOURCE_ROW)])
    execute(value, PRE_LISTING_DAY)
    before = read_rows(engine)
    replay = execute(value, PRE_LISTING_DAY)
    assert (replay["rows_fetched"], replay["rows_saved"], replay["raw_changed"], replay["serving_changed"]) == (1, 2, 0, 0)
    assert replay["null_before_listing_codes"] == ["920964.BJ"] and not replay["already_complete"]
    assert value.connector.call_bounded.call_count == 2
    assert len(listing_queries) == 2
    assert all(list(params.values()) == ["920964.BJ"] for sql, params in listing_queries)
    assert read_rows(engine) == before
    value.connector.call_bounded.return_value = [dict(PRE_LISTING_SOURCE_ROW), {
        **PRE_LISTING_SOURCE_ROW, "ts_code": PRE_LISTING_CODE, "limit_status": 3}]
    recovered = execute(value, PRE_LISTING_DAY)
    assert (recovered["rows_fetched"], recovered["rows_saved"], recovered["raw_changed"], recovered["serving_changed"]) == (2, 2, 1, 1)
    assert "null_before_listing_codes" not in recovered
    assert execute(value, PRE_LISTING_DAY)["already_complete"] is True
    assert value.connector.call_bounded.call_count == 3


def test_one_qualified_missing_target_does_not_hide_an_unqualified_missing_target(before_listing_database):
    engine, factory = before_listing_database
    before = read_rows(engine)
    with pytest.raises(IngestionError) as caught:
        execute(service(factory, []), PRE_LISTING_DAY)
    assert caught.value.structured_error.details["missing_codes"] == ["000001.SZ"]
    assert read_rows(engine) == before


def test_pre_listing_exception_does_not_break_two_table_rollback(before_listing_database):
    engine, factory = before_listing_database
    before = read_rows(engine)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE core_serving.equity_daily_basic ADD CONSTRAINT pre_listing_failure "
                                "CHECK (trade_date <> '2018-12-24'::date OR limit_status IS NULL)"))
    with pytest.raises(Exception, match="pre_listing_failure"):
        execute(service(factory, [dict(PRE_LISTING_SOURCE_ROW)]), PRE_LISTING_DAY)
    assert read_rows(engine) == before


@pytest.mark.parametrize("live_batch_size", [1, 3])
def test_real_update_keeps_all_old_columns_and_zero_is_not_missing(database, monkeypatch, live_batch_size):
    engine, factory = database
    before = read_rows(engine)
    statements = []
    event.listen(engine, "before_cursor_execute", lambda c, u, sql, p, ctx, many: statements.append(sql))
    # Both smaller and larger live settings must retain the frozen size of two.
    monkeypatch.setattr(get_settings(), "sync_batch_size", live_batch_size)
    value = service(factory)
    result = execute(value)
    business_sql = list(statements)
    assert result == {"rows_fetched": 2, "rows_saved": 2, "raw_changed": 2, "serving_changed": 2,
                      "already_complete": False, "source_extra_codes": []}
    updates = [sql for sql in business_sql if sql.startswith("UPDATE ")]
    assert len(updates) == 2
    assert all("updated_at" not in sql and "close" not in sql for sql in updates)
    last_update = max(i for i, sql in enumerate(business_sql) if sql.startswith("UPDATE "))
    assert not any(sql.startswith("SELECT ") for sql in business_sql[last_update + 1:])
    for old, new in zip(before, read_rows(engine), strict=True):
        assert [row["limit_status"] for row in new] == [4, 0, None, None]
        assert [{k: v for k, v in row.items() if k != "limit_status"} for row in old] == [
            {k: v for k, v in row.items() if k != "limit_status"} for row in new]
    raw_reads = [sql for sql in business_sql if sql.startswith("SELECT ") and "raw_tushare.daily_basic" in sql]
    assert len(raw_reads) == 1 and "ts_code, raw_tushare.daily_basic.trade_date) IN" in raw_reads[0]
    assert get_settings().sync_batch_size == live_batch_size
    # New instance represents a process restart. Resume uses persisted values.
    restarted = service(factory)
    assert execute(restarted) == {"rows_fetched": 0, "rows_saved": 2, "raw_changed": 0, "serving_changed": 0,
                                  "already_complete": True, "source_extra_codes": []}
    restarted.connector.call_bounded.assert_not_called()
    assert value.connector.call_bounded.call_args.kwargs["fields"] == DOWNLOAD_FIELDS


def test_fill_ignores_unrequested_valuation_fields_and_does_not_create_payload():
    value = DailyBasicLimitStatusService(session_factory=None, connector=Mock())
    row = {**source_rows()[0], "pe": "not-a-number", "close": "unused"}
    normalized = value._normalize([row], DAY)
    assert normalized == [{"ts_code": "000001.SZ", "trade_date": DAY, "limit_status": 4}]


@pytest.mark.parametrize("field,value,reason", [
    ("ts_code", None, "normalize.required_field_missing:ts_code"),
    ("ts_code", " ", "normalize.empty_not_allowed:ts_code"),
    ("trade_date", None, "normalize.required_field_missing:trade_date"),
    ("trade_date", "not-a-date", "normalize.invalid_date:trade_date"),
])
def test_projected_required_values_keep_existing_rejection_reasons(field, value, reason):
    service_value = DailyBasicLimitStatusService(session_factory=None, connector=Mock())
    row = {**source_rows()[0], field: value}
    with pytest.raises(IngestionError) as caught:
        service_value._normalize([row], DAY)
    assert caught.value.structured_error.details["rejected_reasons"] == {reason: 1}


@pytest.mark.parametrize("field", DOWNLOAD_FIELDS)
def test_missing_projected_field_fails_the_whole_date(database, field):
    engine, factory = database
    rows = source_rows()
    del rows[1][field]
    with pytest.raises(IngestionError) as caught:
        execute(service(factory, rows))
    assert caught.value.structured_error.details["rejected_reasons"] == {
        f"normalize.required_field_missing:{field}": 1}
    assert all(row["limit_status"] is None for values in read_rows(engine) for row in values)


@pytest.mark.parametrize("bad", [None, True, "4", 1.5, -1, 7])
def test_invalid_source_status_rejects_the_entire_date(database, bad):
    engine, factory = database
    value = service(factory, [source_rows()[0], {**source_rows()[1], "limit_status": bad}])
    with pytest.raises(IngestionError) as caught:
        execute(value)
    error = caught.value.structured_error
    assert error.error_code == "normalize.source_validation_failed"
    sample = next(iter(error.details["rejected_samples"].values()))[0]
    assert sample["row"]["ts_code"] == "000002.SZ" and sample["field"] == "limit_status"
    assert error.details["rows_rejected"] == 1
    assert all(row["limit_status"] is None for rows in read_rows(engine) for row in rows)


@pytest.mark.parametrize("variant", ["missing_field", "duplicate", "wrong_date", "missing_code", "empty"])
def test_incomplete_or_wrong_source_never_partially_commits(database, variant):
    engine, factory = database
    rows = source_rows()
    if variant == "missing_field":
        del rows[1]["limit_status"]
    elif variant == "duplicate":
        rows.append(rows[0].copy())
    elif variant == "wrong_date":
        rows[1]["trade_date"] = "20261111"
    elif variant == "missing_code":
        rows = rows[:1]
    else:
        rows = []
    with pytest.raises(IngestionError):
        execute(service(factory, rows))
    assert all(row["limit_status"] is None for values in read_rows(engine) for row in values)


def test_partial_existing_values_and_extra_source_code_are_explained(database):
    engine, factory = database
    with engine.begin() as connection:
        connection.execute(text("UPDATE raw_tushare.daily_basic SET limit_status=4 WHERE trade_date=:day AND ts_code='000001.SZ'"), {"day": DAY})
    result = execute(service(factory, [*source_rows(), {**SOURCE_ROW, "ts_code": "000003.SZ"}]))
    assert (result["rows_fetched"], result["rows_saved"], result["raw_changed"], result["serving_changed"]) == (3, 2, 1, 2)
    assert result["source_extra_codes"] == ["000003.SZ"]
    assert all(len(rows) == 4 for rows in read_rows(engine))


@pytest.mark.parametrize("raw_status,serving_status", [(4, 0), (3, None), (-1, None)])
def test_existing_nonnull_conflicts_are_not_corrected(database, raw_status, serving_status):
    engine, factory = database
    with engine.begin() as connection:
        for table, status in (("raw_tushare.daily_basic", raw_status), ("core_serving.equity_daily_basic", serving_status)):
            connection.execute(text(f"UPDATE {table} SET limit_status=:status WHERE trade_date=:day AND ts_code='000001.SZ'"),
                               {"status": status, "day": DAY})
    before = read_rows(engine)
    with pytest.raises(IngestionError, match="状态"):
        execute(service(factory))
    assert read_rows(engine) == before


def test_second_table_failure_rolls_back_only_current_date(database):
    engine, factory = database
    value = service(factory)
    execute(value)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE core_serving.equity_daily_basic ADD CONSTRAINT stage3_failure CHECK (trade_date <> '2026-11-11'::date OR limit_status IS NULL)"))
    with pytest.raises(Exception, match="stage3_failure"):
        execute(service(factory, source_rows(NEXT_DAY)), NEXT_DAY)
    for rows in read_rows(engine):
        assert [row["limit_status"] for row in rows] == [4, 0, None, None]


def test_cancel_inside_date_rolls_back_both_tables_and_resume_completes(database):
    engine, factory = database
    canceled = False

    def observe(phase, **kw):
        nonlocal canceled
        if phase == "更新原始表":
            canceled = True

    def check():
        if canceled:
            raise IngestionCanceledError("deliberate cancellation")

    with pytest.raises(IngestionCanceledError):
        execute(service(factory), check=check, observe=observe)
    assert all(row["limit_status"] is None for rows in read_rows(engine) for row in rows)
    assert execute(service(factory))["rows_saved"] == 2


def test_commit_reply_failure_stops_without_automatic_recovery(database):
    engine, factory = database

    class LostReply(Session):
        def commit(self):
            super().commit()
            raise RuntimeError("deliberately lost commit reply")

    with pytest.raises(IngestionError) as caught:
        execute(service(sessionmaker(engine, class_=LostReply)))
    assert caught.value.structured_error.error_code == "daily_basic_limit_status.commit_unconfirmed"
    assert "确认原任务已结束" in str(caught.value)
    assert execute(service(factory))["already_complete"] is True


def test_real_planner_uses_calendar_two_aggregate_counts_and_bounded_descriptors(database):
    engine, factory = database
    statements, checkpoints = [], []
    event.listen(engine, "before_cursor_execute", lambda c, u, sql, p, ctx, many: statements.append(sql))
    with factory() as session:
        units = service(factory).plan_dates(session, start_date=DAY, end_date=NEXT_DAY,
            config=CONFIG, check=lambda: None, on_batch=lambda units, total, phase: checkpoints.append((len(units), total)))
    assert [unit["trade_date"] for unit in units] == ["2026-11-10", "2026-11-11"]
    assert all(unit["raw_count"] == unit["serving_count"] == 2 and unit["page_limit"] == 6000 for unit in units)
    assert units[0]["request_params"] == {"trade_date": "20261110"}
    assert checkpoints == [(0, 2), (2, 2)]
    assert len([sql for sql in statements if "count(" in sql.lower()]) == 2
    assert all("limit_status" not in sql for sql in statements)


def test_plan_mismatch_and_frozen_target_mismatch_stop_before_source(database):
    engine, factory = database
    value = service(factory)
    with engine.begin() as connection:
        connection.execute(insert(RawDailyBasic), {**SOURCE_ROW, "ts_code": "000003.SZ", "trade_date": DAY})
    with factory() as session:
        with pytest.raises(IngestionError):
            value.plan_dates(session, start_date=DAY, end_date=NEXT_DAY, config=CONFIG,
                             check=lambda: None, on_batch=lambda *a: None)
    with pytest.raises(IngestionError):
        value.execute_day(payload(raw_count=3), config=CONFIG, check=lambda: None, observe=lambda *a, **k: None)
    value.connector.call_bounded.assert_not_called()


def test_equal_counts_do_not_hide_different_primary_keys(database):
    engine, factory = database
    with engine.begin() as connection:
        connection.execute(text("UPDATE raw_tushare.daily_basic SET ts_code='000003.SZ' WHERE trade_date=:day AND ts_code='000002.SZ'"), {"day": DAY})
    value = service(factory)
    with pytest.raises(IngestionError, match="主键"):
        execute(value)
    value.connector.call_bounded.assert_not_called()
    assert all(row["limit_status"] is None for rows in read_rows(engine) for row in rows)


def test_sql_wait_timeout_honors_cancellation_after_rolling_back_date(database):
    engine, factory = database
    canceled = False

    def on_sql(connection, cursor, sql, params, context, many):
        nonlocal canceled
        if sql.startswith("UPDATE raw_tushare.daily_basic"):
            canceled = True

    def check():
        if canceled:
            raise IngestionCanceledError("cancel received while SQL waits")

    with engine.connect() as lock:
        transaction = lock.begin()
        lock.execute(text("SELECT ts_code FROM raw_tushare.daily_basic WHERE trade_date=:day FOR UPDATE"), {"day": DAY})
        event.listen(engine, "before_cursor_execute", on_sql)
        try:
            with pytest.raises(IngestionCanceledError):
                service(factory).execute_day(payload(), config={**CONFIG, "statement_timeout_seconds": .1},
                                              check=check, observe=lambda *a, **k: None)
        finally:
            event.remove(engine, "before_cursor_execute", on_sql)
            transaction.rollback()
    assert canceled
    assert all(row["limit_status"] is None for rows in read_rows(engine) for row in rows)
