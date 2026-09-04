"""Monthly regression against disposable PostgreSQL, never a configured DB URL."""

from calendar import monthrange
from datetime import date, datetime, timezone
from decimal import Decimal
import subprocess
import sys
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, insert, select, text
from sqlalchemy.orm import Session

from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion.execution_plan import PlanUnitSnapshot
from src.foundation.ingestion.execution_plan import ValidatedDatasetActionRequest
from src.foundation.ingestion.errors import IngestionError
from src.foundation.ingestion.executor import IngestionExecutor
from src.foundation.ingestion.normalizer import NormalizedBatch
from src.foundation.ingestion.run_errors import IngestionCanceledError
from src.foundation.ingestion.writer import DatasetWriter
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.index_daily_serving import IndexDailyServing
from src.foundation.models.core_serving.index_monthly_serving import IndexMonthlyServing
from src.foundation.models.core_serving.index_weekly_serving import IndexWeeklyServing
from src.foundation.models.raw.raw_index_monthly_bar import RawIndexMonthlyBar
from src.foundation.models.raw.raw_index_weekly_bar import RawIndexWeeklyBar
from tests.wealth_watchlist_postgres_support import isolated_postgres


JULY_END = date(2026, 7, 31)
CODE = "000001.SH"
DEFINITION = get_dataset_definition("index_monthly")


@pytest.fixture(scope="module")
def cluster(tmp_path_factory):
    with isolated_postgres(tmp_path_factory.mktemp("index-monthly-postgres")) as engine:
        yield engine


@pytest.fixture
def session(cluster):
    # Each test owns a newly created database inside the disposable cluster.
    database = "monthly_" + uuid4().hex
    with cluster.connect().execution_options(
        isolation_level="AUTOCOMMIT"
    ) as connection:
        connection.exec_driver_sql(f"CREATE DATABASE {database}")
    engine = create_engine(cluster.url.set(database=database))
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE SCHEMA core_serving")
        connection.exec_driver_sql("CREATE SCHEMA raw_tushare")
        for model in (
            TradeCalendar,
            IndexDailyServing,
            IndexMonthlyServing,
            RawIndexMonthlyBar,
            IndexWeeklyServing,
            RawIndexWeeklyBar,
        ):
            model.__table__.create(connection)
        rows = []
        for month in (5, 6, 7, 8, 9):
            for day in range(1, monthrange(2026, month)[1] + 1):
                current = date(2026, month, day)
                rows.append(
                    dict(
                        exchange="SSE",
                        trade_date=current,
                        is_open=current.weekday() < 5,
                    )
                )
        connection.execute(insert(TradeCalendar), rows)
    try:
        with Session(engine) as value:
            yield value
    finally:
        engine.dispose()


def _row(code=CODE, day=JULY_END):
    return dict(
        ts_code=code,
        trade_date=day,
        open=10,
        high=15,
        low=8,
        close=12,
        pre_close=10,
        change=2,
        pct_chg=Decimal("0.2"),
        vol=100,
        amount=1000,
    )


def _existing(session, *, source="derived_daily", day=date(2026, 7, 30), code=CODE):
    row = _row(code, day)
    row.pop("change")
    row.update(period_start_date=day.replace(day=1), source=source, close=11)
    session.execute(insert(IndexMonthlyServing), row)
    session.commit()


def _daily(session, *, code=CODE, month=7, missing=(), bad_field=None, extra_day=None):
    days = [
        date(2026, month, d)
        for d in range(1, monthrange(2026, month)[1] + 1)
        if date(2026, month, d).weekday() < 5 and date(2026, month, d) not in missing
    ]
    if extra_day:
        days.append(extra_day)
    rows = []
    for day in days:
        row = _row(code, day)
        row.pop("change")
        row["source"] = "api"
        if bad_field and day == date(2026, month, 15):
            row[bad_field] = None
        rows.append(row)
    session.execute(insert(IndexDailyServing), rows)
    session.commit()


def _writer(
    session, mocker, *, active=(CODE,), now=datetime(2026, 8, 1, tzinfo=timezone.utc)
):
    writer = DatasetWriter(session)
    mocker.patch.object(
        writer.dao.index_series_active, "list_active_codes", return_value=list(active)
    )
    mocker.patch(
        "src.foundation.ingestion.writer.datetime", wraps=datetime
    ).now.return_value = now
    return writer


def _unit(day=JULY_END, *, code=None):
    return PlanUnitSnapshot(
        unit_id=f"index_monthly:{day}",
        dataset_key="index_monthly",
        source_key="tushare",
        trade_date=day,
        request_params={
            "trade_date": day.strftime("%Y%m%d"),
            **({"ts_code": code} if code else {}),
        },
        progress_context={},
        pagination_policy="offset_limit",
        page_limit=1000,
    )


def _write(writer, *, rows=(), day=JULY_END, code=None, profile="point_incremental"):
    return writer.write(
        definition=DEFINITION,
        batch=NormalizedBatch(
            unit_id="monthly",
            rows_normalized=list(rows),
            rows_rejected=0,
            rejected_reasons={},
        ),
        plan_unit=_unit(day, code=code),
        run_profile=profile,
    )


@pytest.mark.parametrize("explicit", [False, True])
def test_api_corrects_old_partial_month_and_revisions_are_idempotent(
    session, mocker, explicit
):
    _existing(session)
    writer = _writer(session, mocker)
    code = CODE if explicit else None
    result = _write(writer, rows=[_row()], code=code, profile="range_rebuild")
    session.commit()
    assert result.rows_written == 1
    rows = session.execute(select(IndexMonthlyServing)).scalars().all()
    assert len(rows) == 1
    assert (rows[0].trade_date, rows[0].source, rows[0].close) == (
        JULY_END,
        "api",
        Decimal(12),
    )
    revised = {**_row(), "close": 13}
    for _ in range(2):
        _write(writer, rows=[revised], code=code)
        session.commit()
    session.expire_all()
    assert session.scalar(select(IndexMonthlyServing.close)) == 13
    assert session.scalar(select(RawIndexMonthlyBar.close)) == 13


@pytest.mark.parametrize("explicit", [False, True])
def test_empty_response_preserves_api_and_does_not_derive(session, mocker, explicit):
    _existing(session, source="api", day=JULY_END)
    _daily(session)
    result = _write(
        _writer(session, mocker),
        code=CODE if explicit else None,
        profile="range_rebuild",
    )
    session.commit()
    row = session.scalar(select(IndexMonthlyServing))
    assert (row.source, row.close) == ("api", Decimal(11))
    assert result.rows_written == 0
    assert session.scalar(select(RawIndexMonthlyBar.ts_code)) is None


@pytest.mark.parametrize(
    "now,allowed",
    [
        (datetime(2026, 7, 15, tzinfo=timezone.utc), False),
        (datetime(2026, 7, 31, 15, 59, 59, tzinfo=timezone.utc), False),
        (datetime(2026, 7, 31, 16, 0, tzinfo=timezone.utc), True),
    ],
)
def test_derivation_waits_for_beijing_next_month(session, mocker, now, allowed):
    _daily(session)
    result = _write(_writer(session, mocker, now=now))
    session.commit()
    assert result.rows_written == int(allowed)
    row = session.scalar(select(IndexMonthlyServing))
    if allowed:
        assert (row.trade_date, row.period_start_date, row.source) == (
            JULY_END,
            date(2026, 7, 1),
            "derived_daily",
        )
        assert (
            row.open,
            row.high,
            row.low,
            row.close,
            row.change_amount,
            row.pct_chg,
        ) == (10, 15, 8, 12, 2, Decimal(".2"))
        assert (row.vol, row.amount) == (230000, 23000000)
    else:
        assert row is None
    assert session.scalar(select(RawIndexMonthlyBar.ts_code)) is None


@pytest.mark.parametrize("missing", [date(2026, 7, 1), date(2026, 7, 15), JULY_END])
def test_incomplete_daily_calendar_blocks_only_that_index(session, mocker, missing):
    _daily(session, missing=(missing,))
    _daily(session, code="000002.SH")
    _existing(session)
    result = _write(_writer(session, mocker, active=(CODE, "000002.SH")))
    session.commit()
    assert result.rows_written == 1
    assert (
        session.scalar(
            select(IndexMonthlyServing.close).where(IndexMonthlyServing.ts_code == CODE)
        )
        == 11
    )
    assert (
        session.scalar(
            select(IndexMonthlyServing.source).where(
                IndexMonthlyServing.ts_code == "000002.SH"
            )
        )
        == "derived_daily"
    )


@pytest.mark.parametrize(
    "field", ["open", "high", "low", "close", "pre_close", "vol", "amount"]
)
def test_null_calculation_field_blocks_derivation(session, mocker, field):
    _daily(session, bad_field=field)
    assert _write(_writer(session, mocker)).rows_written == 0


def test_same_day_count_with_wrong_date_set_is_not_complete(session, mocker):
    _daily(session, missing=(date(2026, 7, 15),), extra_day=date(2026, 7, 18))
    assert _write(_writer(session, mocker)).rows_written == 0


def test_full_month_response_preserves_absent_api_and_filters_inactive(session, mocker):
    _existing(session, source="api", day=JULY_END, code="000002.SH")
    _daily(session, code="000003.SH")
    writer = _writer(session, mocker, active=(CODE, "000002.SH", "000003.SH"))
    result = _write(writer, rows=[_row(), _row("999999.SH")])
    session.commit()
    assert result.rows_written == 2
    assert set(session.scalars(select(RawIndexMonthlyBar.ts_code))) == {
        CODE,
        "999999.SH",
    }
    assert dict(
        session.execute(
            select(IndexMonthlyServing.ts_code, IndexMonthlyServing.source)
        ).all()
    ) == {
        CODE: "api",
        "000002.SH": "api",
        "000003.SH": "derived_daily",
    }
    assert (
        session.scalar(
            select(IndexMonthlyServing.close).where(
                IndexMonthlyServing.ts_code == "000002.SH"
            )
        )
        == 11
    )


@pytest.mark.parametrize("has_source", [False, True])
def test_explicit_non_active_code_never_writes_serving(session, mocker, has_source):
    _daily(session, code="999999.SH")
    result = _write(
        _writer(session, mocker),
        code="999999.SH",
        rows=[_row("999999.SH")] if has_source else [],
    )
    session.commit()
    assert result.rows_written == 0
    assert session.scalar(select(IndexMonthlyServing.ts_code)) is None
    assert (
        session.scalar(select(RawIndexMonthlyBar.ts_code)) is not None
    ) == has_source


def test_source_row_is_accepted_on_month_end_before_derivation_is_allowed(
    session, mocker
):
    writer = _writer(
        session, mocker, now=datetime(2026, 7, 31, 12, tzinfo=timezone.utc)
    )
    assert _write(writer, rows=[_row()]).rows_written == 1
    session.commit()
    assert session.scalar(select(IndexMonthlyServing.source)) == "api"


@pytest.mark.parametrize("explicit", [False, True])
def test_complete_daily_data_corrects_and_refreshes_old_derived_month(
    session, mocker, explicit
):
    _existing(session)
    _daily(session)
    writer = _writer(session, mocker)
    for close in (12, 14):
        session.execute(
            text(
                "UPDATE core_serving.index_daily_serving SET close=:close WHERE trade_date=:day"
            ),
            {"close": close, "day": JULY_END},
        )
        session.commit()
        assert (
            _write(
                writer, code=CODE if explicit else None, profile="range_rebuild"
            ).rows_written
            == 1
        )
        session.commit()
        row = session.scalar(select(IndexMonthlyServing))
        assert (row.trade_date, row.close, row.source) == (
            JULY_END,
            close,
            "derived_daily",
        )


def test_month_end_weekend_still_waits_until_next_calendar_month(session, mocker):
    _daily(session, month=5)
    writer = _writer(
        session, mocker, now=datetime(2026, 5, 31, 15, 59, tzinfo=timezone.utc)
    )
    assert _write(writer, day=date(2026, 5, 29)).rows_written == 0
    mocker.patch(
        "src.foundation.ingestion.writer.datetime", wraps=datetime
    ).now.return_value = datetime(2026, 5, 31, 16, tzinfo=timezone.utc)
    assert _write(writer, day=date(2026, 5, 29)).rows_written == 1


def test_incomplete_calendar_and_invalid_anchor_cannot_derive(session, mocker):
    _daily(session)
    writer = _writer(session, mocker)
    assert _write(writer, day=date(2026, 7, 30)).rows_written == 0
    # This deletes only one synthetic calendar row in this disposable test DB.
    session.execute(
        text("DELETE FROM core_serving.trade_calendar WHERE trade_date='2026-07-31'")
    )
    session.commit()
    assert _write(writer).rows_written == 0


@pytest.mark.parametrize(
    "field,value",
    [("pre_close", 0), ("open", Decimal("NaN")), ("amount", Decimal("NaN"))],
)
def test_invalid_numeric_values_block_derivation(session, mocker, field, value):
    _daily(session)
    session.execute(
        IndexDailyServing.__table__.update()
        .where(IndexDailyServing.trade_date == JULY_END)
        .values({field: value})
    )
    session.commit()
    assert _write(_writer(session, mocker)).rows_written == 0


def test_api_arriving_after_eligibility_check_cannot_be_downgraded(session, mocker):
    _daily(session)
    writer = _writer(session, mocker)
    rows = writer._build_index_period_derived_rows_for_codes(
        definition=DEFINITION, trade_date=JULY_END, ts_codes=[CODE]
    )
    assert len(rows) == 1
    # Model a source write landing between eligibility read and conditional upsert.
    with Session(session.get_bind()) as other:
        _existing(other, source="api", day=JULY_END)
    assert (
        writer._upsert_index_monthly_serving_rows(
            core_dao=writer.dao.index_monthly_serving, rows=rows
        )
        == 0
    )
    session.commit()
    assert session.scalar(select(IndexMonthlyServing.close)) == 11


def _request():
    return ValidatedDatasetActionRequest(
        request_id="monthly-test",
        dataset_key="index_monthly",
        action="maintain",
        run_profile="range_rebuild",
        trigger_source="test",
        params={},
        source_key=None,
        trade_date=None,
        start_date=date(2026, 6, 30),
        end_date=JULY_END,
        run_id=1,
    )


def _executor(session, mocker, connector):
    mocker.patch(
        "src.foundation.ingestion.source_client.create_source_connector",
        return_value=connector,
    )
    executor = IngestionExecutor(session)
    executor.writer = _writer(session, mocker)
    return executor


def _connector(mocker, *, fail_offset=None, bad_july=False):
    calls = []

    def call(*, api_name, params, fields):
        assert api_name == "index_monthly"
        calls.append(dict(params))
        day = datetime.strptime(params["trade_date"], "%Y%m%d").date()
        if fail_offset is not None and params["offset"] >= fail_offset:
            raise ValueError("synthetic source failure")
        if params["offset"] > 0:
            return []
        row = _row(day=day)
        if bad_july and day == JULY_END:
            row["close"] = 999
        if fail_offset:
            return [{**row, "ts_code": f"{i:06d}.SH"} for i in range(params["limit"])]
        return [row]

    return mocker.Mock(call=call), calls


@pytest.mark.parametrize("fail_offset", [0, 1000])
def test_source_first_or_later_page_failure_never_writes_or_derives(
    session, mocker, fail_offset
):
    _existing(session)
    _daily(session)
    connector, calls = _connector(mocker, fail_offset=fail_offset)
    executor = _executor(session, mocker, connector)
    spy = mocker.spy(executor.writer, "write")
    with pytest.raises(IngestionError, match="synthetic source failure"):
        executor.run(request=_request(), definition=DEFINITION, units=(_unit(),))
    spy.assert_not_called()
    assert [call["offset"] for call in calls] == (
        [0] if fail_offset == 0 else [0, 1000]
    )
    assert session.scalar(select(RawIndexMonthlyBar.ts_code)) is None
    assert session.scalar(select(IndexMonthlyServing.trade_date)) == date(2026, 7, 30)


def test_failed_serving_write_rolls_back_only_current_month(session, mocker):
    _existing(session)
    session.execute(
        text("ALTER TABLE core_serving.index_monthly_serving ADD CHECK (close < 100)")
    )
    session.commit()
    connector, _ = _connector(mocker, bad_july=True)
    executor = _executor(session, mocker, connector)
    with pytest.raises(IngestionError, match="check constraint"):
        executor.run(
            request=_request(),
            definition=DEFINITION,
            units=(_unit(date(2026, 6, 30)), _unit()),
        )
    assert set(session.scalars(select(RawIndexMonthlyBar.trade_date))) == {
        date(2026, 6, 30)
    }
    assert set(session.scalars(select(IndexMonthlyServing.trade_date))) == {
        date(2026, 6, 30),
        date(2026, 7, 30),
    }


def test_cancel_after_commit_preserves_first_month_and_new_session_can_replay(
    session, mocker
):
    connector, calls = _connector(mocker)
    executor = _executor(session, mocker, connector)
    progress = []

    def report(snapshot, message):
        with Session(session.get_bind()) as reader:
            assert reader.scalar(select(RawIndexMonthlyBar.trade_date)) == date(
                2026, 6, 30
            )
        progress.append(snapshot.unit_done)

    units = (_unit(date(2026, 6, 30)), _unit())
    with pytest.raises(IngestionCanceledError):
        executor.run(
            request=_request(),
            definition=DEFINITION,
            units=units,
            cancel_checker=lambda run_id: bool(progress),
            progress_reporter=report,
        )
    assert len(calls) == 1
    assert progress == [1]
    session.close()
    with Session(session.get_bind()) as resumed:
        summary = _executor(resumed, mocker, connector).run(
            request=_request(), definition=DEFINITION, units=units
        )
        assert (summary.unit_done, summary.rows_committed, summary.rows_rejected) == (
            2,
            2,
            0,
        )
        assert len(list(resumed.scalars(select(IndexMonthlyServing)))) == 2


def test_process_exit_keeps_committed_month_and_rolls_back_uncommitted_month(session):
    _existing(session)
    script = """
import os, sys
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from src.foundation.ingestion.writer import DatasetWriter
from tests.test_index_monthly_postgres import _write, _row, CODE
engine = create_engine(sys.argv[1])
with Session(engine) as session:
    writer = DatasetWriter(session)
    writer.dao.index_series_active.list_active_codes = lambda resource: [CODE]
    _write(writer, rows=[_row(day=date(2026, 6, 30))], day=date(2026, 6, 30))
    session.commit()
    _write(writer, rows=[_row()])
    os._exit(17)
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            session.get_bind().url.render_as_string(hide_password=False),
        ],
        timeout=30,
        capture_output=True,
    )
    assert result.returncode == 17, result.stderr.decode()
    assert set(session.scalars(select(RawIndexMonthlyBar.trade_date))) == {
        date(2026, 6, 30)
    }
    assert set(session.scalars(select(IndexMonthlyServing.trade_date))) == {
        date(2026, 6, 30),
        date(2026, 7, 30),
    }


def test_source_batch_cannot_bypass_month_end_validation_through_cache(session, mocker):
    writer = _writer(session, mocker, active=(CODE, "000002.SH"))
    with pytest.raises(IngestionError, match="月末交易日"):
        _write(writer, rows=[_row(), _row("000002.SH", date(2026, 7, 30))])
    session.rollback()
    assert session.scalar(select(RawIndexMonthlyBar.ts_code)) is None


def test_rejected_source_row_is_not_treated_as_source_absence(session, mocker):
    _daily(session)
    writer = _writer(session, mocker)
    result = writer.write(
        definition=DEFINITION,
        batch=NormalizedBatch(
            unit_id="monthly",
            rows_normalized=[],
            rows_rejected=1,
            rejected_reasons={"normalize.required_field_missing:ts_code": 1},
        ),
        plan_unit=_unit(),
        run_profile="point_incremental",
    )
    assert result.rows_written == 0


def test_closed_day_row_outside_first_last_open_days_is_not_aggregated(session, mocker):
    _daily(session, month=5, extra_day=date(2026, 5, 31))
    assert _write(_writer(session, mocker), day=date(2026, 5, 29)).rows_written == 0


def test_weekly_sql_derivation_keeps_existing_partial_week_behavior(session, mocker):
    _daily(session)
    writer = _writer(session, mocker, now=datetime(2026, 7, 30, tzinfo=timezone.utc))
    day = date(2026, 7, 30)
    result = writer.write(
        definition=get_dataset_definition("index_weekly"),
        batch=NormalizedBatch(
            unit_id="weekly", rows_normalized=[], rows_rejected=0, rejected_reasons={}
        ),
        plan_unit=PlanUnitSnapshot(
            unit_id="weekly",
            dataset_key="index_weekly",
            source_key="tushare",
            trade_date=day,
            request_params={"trade_date": "20260730"},
            progress_context={},
        ),
        run_profile="point_incremental",
    )
    session.commit()
    assert result.rows_written == 1
    row = session.scalar(select(IndexWeeklyServing))
    assert (row.period_start_date, row.trade_date, row.source) == (
        date(2026, 7, 27),
        day,
        "derived_daily",
    )
    assert (row.vol, row.amount, row.close) == (40000, 4000000, 12)
