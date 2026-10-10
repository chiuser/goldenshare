"""Isolated physical publication/restart tests; no production schemas or source calls."""

from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from src.foundation.dao.stock_weekly_adj_delivery_dao import StockWeeklyAdjDeliveryDAO
from src.foundation.datasets.stock_weekly_adj_contracts import (
    SOURCE_FIELDS,
    WeeklyAdjContractError,
)
from src.foundation.ingestion.errors import IngestionSourceError, IngestionWriteError
from src.foundation.ingestion.execution_plan import (
    DatasetActionRequest,
    DatasetTimeInput,
)
from src.foundation.ingestion.executor import IngestionExecutor
from src.foundation.ingestion.resolver import DatasetActionResolver
from src.foundation.ingestion.run_errors import IngestionCanceledError
from src.foundation.ingestion.source_client import DatasetSourceClient, SourcePageResult
from src.foundation.ingestion.stock_weekly_adj_delivery import delivery_record
from src.foundation.ingestion.stock_weekly_adj_execution import publisher_lock
from src.foundation.ingestion.stock_weekly_adj_planning import (
    load_changed_codes,
    resolve_weekly_adj_units,
)
from src.foundation.ingestion.stock_weekly_adj_scope import freeze_weekly_adj_execution
from src.foundation.models.core.stock_weekly_adj_delivery import (
    StockWeeklyAdjDelivery as Delivery,
)
from src.foundation.models.core.trade_calendar import TradeCalendar as Calendar
from src.foundation.models.core_serving.equity_adj_factor import (
    EquityAdjFactor as Factor,
)
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar as Daily
from src.foundation.models.core_serving.stk_period_bar_adj import (
    StkPeriodBarAdj as Serving,
)
from src.foundation.models.raw.raw_stk_period_bar_adj import RawStkPeriodBarAdj as Raw
from test_stock_weekly_adj_p1_contracts import weekly_definition

CODE = "000001.SZ"
OLD = date(2026, 6, 5)
WEEK = date(2026, 10, 9)
NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)


def row(day=OLD, code=CODE, close="10", qfq="5", basis=WEEK):
    return {
        **dict.fromkeys(SOURCE_FIELDS, Decimal("1.0000")),
        "ts_code": code,
        "trade_date": day,
        "end_date": basis,
        "freq": "week",
        "close": Decimal(close),
        "close_qfq": Decimal(qfq),
    }


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/main.db")

    @event.listens_for(engine, "connect")
    def attach(conn, record):
        conn.create_function("now", 0, lambda: "2026-10-10 00:00:00")
        for name in ("core", "core_serving", "raw_tushare"):
            conn.execute(f"ATTACH DATABASE '{tmp_path}/{name}.db' AS {name}")

    for model in (Delivery, Calendar, Factor, Daily, Raw, Serving):
        model.__table__.create(engine)
    with Session(engine) as s:
        # Historical sample and one pending complete week, including prior open day.
        for start, end in ((OLD - timedelta(days=4), OLD), (date(2026, 9, 21), WEEK)):
            day = start
            while day <= end:
                s.add(
                    Calendar(exchange="SSE", trade_date=day, is_open=day.weekday() < 5)
                )
                day += timedelta(days=1)
        s.add(
            Daily(ts_code=CODE, trade_date=OLD, close=Decimal("10"), source="tushare")
        )
        s.add(Factor(ts_code=CODE, trade_date=OLD, adj_factor=Decimal("1")))
        for day in (date(2026, 10, 2), *(date(2026, 10, n) for n in range(5, 10))):
            s.add(
                Daily(
                    ts_code=CODE, trade_date=day, close=Decimal("20"), source="tushare"
                )
            )
            s.add(
                Factor(
                    ts_code=CODE,
                    trade_date=day,
                    adj_factor=Decimal("1") if day.day in (2, 5) else Decimal("2"),
                )
            )
        s.add(Raw(**row(qfq="10")))
        s.add(
            Serving(
                **{
                    ("change_amount" if k == "change" else k): v
                    for k, v in row(qfq="10").items()
                }
            )
        )
        s.add(Raw(**{**row(), "freq": "month"}))
        s.commit()
    yield engine
    engine.dispose()


@contextmanager
def isolated_lock(engine, policy):
    # Test replacement only. Production refuses SQLite and always uses PG session locks.
    yield


def requested(
    *, mode="range", trigger="manual", start=OLD, end=WEEK, code=CODE, previous=None
):
    definition = weekly_definition()
    filters = {"ts_code": code} if code else {}
    from src.foundation.ingestion.validator import DatasetRequestValidator

    action = DatasetActionRequest(
        definition.dataset_key,
        "maintain",
        DatasetTimeInput(
            mode,
            trade_date=end if mode == "point" else None,
            start_date=start if mode == "range" else None,
            end_date=end if mode == "range" else None,
        ),
        filters=filters,
        trigger_source=trigger,
        run_id=17,
    )
    validated = DatasetRequestValidator().validate(
        request=action,
        definition=definition,
        run_profile="range_rebuild" if mode == "range" else "point_incremental",
    )
    scope = {
        "mode": mode,
        "start": (start if mode == "range" else end).isoformat(),
        "end": end.isoformat(),
    }
    context = freeze_weekly_adj_execution(
        definition,
        scope=scope,
        filters={
            k: v.isoformat() if type(v) is date else v
            for k, v in validated.params.items()
        },
        trigger_source=trigger,
        previous=previous,
    )
    return replace(validated, execution_context=context)


def planned(db, request=None):
    definition = weekly_definition()
    with Session(db) as s:
        req, units = resolve_weekly_adj_units(
            s, request or requested(), definition, now=NOW
        )
    return definition, req, units


def seed_frontier(db):
    definition, req, units = planned(db)
    ctx = req.execution_context
    payload = {"header": {"unit_count": 0, "total_payload_bytes": 0}, "unit_ids": []}
    record = delivery_record(
        context=ctx,
        kind="bootstrap_closed",
        unit_id="bootstrap_closed",
        payload=payload,
    )
    record["cutoff_week"] = date(2026, 10, 2)
    record["factor_scan_end"] = date(2026, 10, 2)
    with Session(db) as s:
        StockWeeklyAdjDeliveryDAO(s).append(
            record, definition.planning.weekly_adj_policy
        )
        s.commit()


def fake_pages(rows_by_unit, *, failure=None, after_page=None):
    def iterate(*, definition, unit, control):
        control.check()
        control.fetching(1, 0)
        if failure:
            raise failure
        rows = rows_by_unit(unit)
        yield SourcePageResult(
            unit_id=unit.unit_id,
            page_number=1,
            offset=0,
            rows_raw=rows,
            retry_count=0,
            latency_ms=0,
            is_short_page=True,
        )
        if after_page:
            after_page()
        control.check()

    return iterate


def execute(
    db, monkeypatch, definition, req, units, pages, *, cancel=None, progress=None
):
    monkeypatch.setattr(
        "src.foundation.ingestion.stock_weekly_adj_execution.publisher_lock",
        isolated_lock,
    )
    with Session(db) as s:
        exe = IngestionExecutor(s)
        exe.source_client.iter_weekly_adj_pages = pages
        return exe.run(
            request=req,
            definition=definition,
            units=units,
            cancel_checker=cancel,
            progress_reporter=progress,
        )


def test_daily_union_two_changes_new_listing_and_one_grouped_min(db):
    with Session(db) as s:
        # A second change returns to its earlier factor: compare each day, not endpoints.
        s.get(Factor, (CODE, WEEK)).adj_factor = Decimal("1")
        for day in (date(2026, 10, 8), WEEK):
            s.add(Daily(ts_code="999999.SZ", trade_date=day, source="tushare"))
            s.add(Factor(ts_code="999999.SZ", trade_date=day, adj_factor=Decimal("1")))
        s.commit()
        changes, start, end, first = load_changed_codes(
            s, WEEK, weekly_definition().planning.weekly_adj_policy
        )
        assert changes == {CODE: (OLD, Decimal("1.00000000"))}
        assert (start, end, first) == (date(2026, 10, 5), WEEK, 1)
        s.delete(s.get(Factor, (CODE, date(2026, 10, 7))))
        s.commit()
        with pytest.raises(WeeklyAdjContractError, match="缺少复权因子"):
            load_changed_codes(s, WEEK, weekly_definition().planning.weekly_adj_policy)


def test_scheduler_needs_bootstrap_and_picks_oldest_debt(db):
    with Session(db) as s:
        with pytest.raises(WeeklyAdjContractError, match="完整对账"):
            resolve_weekly_adj_units(
                s,
                requested(mode="point", trigger="schedule", code=None),
                weekly_definition(),
                now=NOW,
            )
    seed_frontier(db)
    definition, req, units = planned(
        db, requested(mode="point", trigger="schedule", code=None)
    )
    assert len(units) == 2
    assert units[0].request_params == {"freq": "week", "trade_date": "20261009"}
    assert units[1].request_params == {
        "freq": "week",
        "ts_code": CODE,
        "start_date": "20260605",
        "end_date": "20261009",
    }
    assert (
        req.execution_context["business_plan"]["metadata"]["factor_scan_end"]
        == "2026-10-09"
    )


def test_raw_serving_receipt_same_commit_precision_and_replay(db, monkeypatch):
    definition, req, units = planned(db)
    seen = []

    def pages(unit):
        seen.append(unit.unit_id)
        return [row(), row()]

    result = execute(
        db,
        monkeypatch,
        definition,
        req,
        units,
        fake_pages(pages),
        progress=lambda *_: (_ for _ in ()).throw(RuntimeError("ops down")),
    )
    assert (
        result.unit_done,
        result.rows_fetched,
        result.rows_written,
        result.rows_deduplicated,
    ) == (1, 2, 1, 1)
    with Session(db) as s:
        assert s.get(Raw, (CODE, OLD, "week")).close_qfq == Decimal("5")
        assert s.get(Serving, (CODE, OLD, "week")).close_qfq == Decimal("5")
        assert s.get(Raw, (CODE, OLD, "month")).close_qfq == Decimal("5")
        receipt = StockWeeklyAdjDeliveryDAO(s).get_record(
            batch_id=req.execution_context["execution_token"],
            record_kind="unit",
            unit_id=units[0].unit_id,
        )
        assert receipt.payload["rows"][0]["close_qfq"] == "5.0000"
        assert (
            "change" in receipt.payload["rows"][0]
            and "change_amount" not in receipt.payload["rows"][0]
        )
        assert (
            s.scalar(
                select(Delivery.revision).where(Delivery.record_kind == "batch_closed")
            )
            is not None
        )
    result2 = execute(db, monkeypatch, definition, req, units, fake_pages(pages))
    assert seen == [units[0].unit_id] and result2.rows_committed == 1


def test_cancel_before_commit_rolls_back_all_and_resume_uses_receipt(db, monkeypatch):
    definition, req, units = planned(db)
    canceled = [False]
    pages = fake_pages(
        lambda _: [row()], after_page=lambda: canceled.__setitem__(0, True)
    )
    with pytest.raises(IngestionCanceledError):
        execute(
            db, monkeypatch, definition, req, units, pages, cancel=lambda _: canceled[0]
        )
    with Session(db) as s:
        assert s.get(Raw, (CODE, OLD, "week")).close_qfq == Decimal("10")
        assert (
            s.scalar(select(Delivery.revision).where(Delivery.record_kind == "unit"))
            is None
        )
        restored, restored_units = resolve_weekly_adj_units(
            s,
            requested(previous=req.execution_context, trigger="retry"),
            definition,
            now=NOW,
        )
    result = execute(
        db,
        monkeypatch,
        definition,
        restored,
        restored_units,
        fake_pages(lambda _: [row()]),
    )
    assert result.unit_done == 1


def test_process_exit_after_commit_retains_progress_then_resumes_remaining(
    db, monkeypatch
):
    seed_frontier(db)
    definition, req, units = planned(
        db, requested(mode="point", trigger="schedule", code=None)
    )
    calls = []

    def rows(unit):
        calls.append(unit.unit_id)
        if len(calls) == 2:
            raise SystemExit("worker terminated after one committed unit")
        return [row(WEEK, close="20", qfq="20")]

    with pytest.raises(SystemExit):
        execute(db, monkeypatch, definition, req, units, fake_pages(rows))
    with Session(db) as s:
        assert s.scalar(select(func_count()).where(Delivery.record_kind == "unit")) == 1
        restored, restored_units = resolve_weekly_adj_units(
            s,
            requested(mode="point", trigger="schedule", code=None),
            definition,
            now=NOW,
        )
        assert (
            restored.execution_context["execution_token"]
            == req.execution_context["execution_token"]
        )
        assert not s.scalar(
            select(Delivery.revision).where(Delivery.record_kind == "batch_closed")
        )
    snapshots = []
    result = execute(
        db,
        monkeypatch,
        definition,
        restored,
        restored_units,
        fake_pages(lambda _: [row()]),
        progress=lambda snap, msg: snapshots.append(snap.unit_done),
    )
    assert result.unit_done == 2 and snapshots[0] >= 1
    assert snapshots == sorted(snapshots)


def func_count():
    from sqlalchemy import func

    return func.count(Delivery.revision)


@pytest.mark.parametrize(
    "bad",
    [
        row(qfq="10"),
        {**row(), "freq": "month"},
        row(code="600018.SH"),
        {**row(), "close": Decimal("1.12345")},
    ],
)
def test_bad_basis_scope_precision_never_publishes(db, monkeypatch, bad):
    definition, req, units = planned(db)
    with pytest.raises(IngestionWriteError):
        execute(db, monkeypatch, definition, req, units, fake_pages(lambda _: [bad]))
    with Session(db) as s:
        assert s.get(Raw, (CODE, OLD, "week")).close_qfq == Decimal("10")
        assert (
            s.scalar(select(Delivery.revision).where(Delivery.record_kind == "unit"))
            is None
        )


def test_source_empty_preserves_keys_payload_and_classification(db, monkeypatch):
    definition, req, units = planned(db)
    result = execute(db, monkeypatch, definition, req, units, fake_pages(lambda _: []))
    assert result.rows_committed == 0
    with Session(db) as s:
        receipt = StockWeeklyAdjDeliveryDAO(s).get_record(
            batch_id=req.execution_context["execution_token"],
            record_kind="unit",
            unit_id=units[0].unit_id,
        )
        assert (
            receipt.outcome == "source_empty_preserved" and receipt.rows_preserved == 1
        )
        assert receipt.payload == {"rows": []}
        assert receipt.reason_summary["preserved_keys"] == [
            {"ts_code": CODE, "trade_date": "20260605"}
        ]
        assert s.get(Raw, (CODE, OLD, "week")).close_qfq == Decimal("10")


def test_source_failure_is_not_empty_business_success(db, monkeypatch):
    definition, req, units = planned(db)
    with pytest.raises(RuntimeError, match="network"):
        execute(
            db,
            monkeypatch,
            definition,
            req,
            units,
            fake_pages(lambda _: [], failure=RuntimeError("network")),
        )
    with Session(db) as s:
        assert (
            s.scalar(select(Delivery.revision).where(Delivery.record_kind == "unit"))
            is None
        )
        assert (
            s.scalar(
                select(Delivery.revision).where(Delivery.record_kind == "batch_closed")
            )
            is None
        )


def test_production_lock_never_uses_sqlite(db):
    with pytest.raises(WeeklyAdjContractError, match="PostgreSQL"):
        with publisher_lock(db, weekly_definition().planning.weekly_adj_policy):
            pass


def test_resolver_reads_only_and_returns_effective_units(db, monkeypatch):
    definition = weekly_definition()
    monkeypatch.setattr(
        "src.foundation.ingestion.resolver.get_dataset_definition", lambda _: definition
    )
    statements = []

    @event.listens_for(db, "before_cursor_execute")
    def sql(conn, cursor, statement, parameters, context, many):
        statements.append(statement)

    with Session(db) as s:
        plan = DatasetActionResolver(s).build_plan(
            DatasetActionRequest(
                definition.dataset_key,
                "maintain",
                DatasetTimeInput("range", start_date=OLD, end_date=WEEK),
                filters={"ts_code": CODE},
            )
        )
        assert len(plan.units) == 1 and "business_plan" in plan.execution_context
    assert all(
        not sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        for sql in statements
    )


def test_bounded_pages_full_then_empty_and_page_budget(monkeypatch):
    definition = weekly_definition()
    policy = replace(
        definition.planning.weekly_adj_policy, max_rows_per_unit=2, max_pages=2
    )
    definition = replace(
        definition,
        planning=replace(
            definition.planning, weekly_adj_policy=policy, max_source_rows_per_unit=2
        ),
    )
    from src.foundation.ingestion.stock_weekly_adj_scope import (
        build_weekly_adj_requested_units,
    )

    req = requested()
    unit = replace(
        build_weekly_adj_requested_units(req, weekly_definition())[0],
        page_limit=1,
        max_source_rows_per_unit=2,
    )
    seen = []

    def call(**kw):
        seen.append(kw)
        return [row()] if kw["params"]["offset"] == 0 else []

    monkeypatch.setattr(
        "src.foundation.ingestion.source_client.create_source_connector",
        lambda _: SimpleNamespace(call_bounded=call),
    )
    control = SimpleNamespace(
        check=lambda: None,
        poll=lambda: None,
        fetching=lambda *_: None,
        tick=lambda: None,
    )
    pages = list(
        DatasetSourceClient().iter_weekly_adj_pages(
            definition=definition, unit=unit, control=control
        )
    )
    assert [p.offset for p in pages] == [0, 1] and pages[-1].is_short_page
    assert all(
        c["response_contract"] == "stock_weekly_adj/v1"
        and c["fields"] == SOURCE_FIELDS
        and c["timeout"] == 20
        for c in seen
    )
    monkeypatch.setattr(
        "src.foundation.ingestion.source_client.create_source_connector",
        lambda _: SimpleNamespace(call_bounded=lambda **_: [row()]),
    )
    with pytest.raises(IngestionSourceError, match="末页"):
        list(
            DatasetSourceClient().iter_weekly_adj_pages(
                definition=definition, unit=unit, control=control
            )
        )


def test_factor_changes_during_suspension_are_not_lost(db):
    with Session(db) as s:
        halted = "600018.SH"
        s.add(Raw(**row(code=halted)))
        s.add(Daily(ts_code=halted, trade_date=OLD, source="tushare"))
        for day in (date(2026, 10, 2), *(date(2026, 10, n) for n in range(5, 10))):
            s.add(
                Factor(
                    ts_code=halted,
                    trade_date=day,
                    adj_factor=Decimal("1") if day.day in (2, 5) else Decimal("2"),
                )
            )
        s.commit()
        changes, *_ = load_changed_codes(
            s, WEEK, weekly_definition().planning.weekly_adj_policy
        )
        assert halted in changes and changes[halted][0] == OLD


def test_complete_factors_do_not_scan_market_daily_history(db):
    statements = []

    def observe(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())

    event.listen(db, "before_cursor_execute", observe)
    try:
        with Session(db) as session:
            changes, *_ = load_changed_codes(
                session, WEEK, weekly_definition().planning.weekly_adj_policy
            )
            assert CODE in changes
    finally:
        event.remove(db, "before_cursor_execute", observe)
    assert not any("equity_daily_bar" in s and "group by" in s for s in statements)


def test_partial_preserves_missing_keys_and_stale_basis_rolls_back(db, monkeypatch):
    with Session(db) as s:
        s.add(Raw(**row(date(2026, 6, 12), qfq="10")))
        s.commit()
    definition, req, units = planned(db)
    execute(db, monkeypatch, definition, req, units, fake_pages(lambda _: [row()]))
    with Session(db) as s:
        record = StockWeeklyAdjDeliveryDAO(s).get_record(
            batch_id=req.execution_context["execution_token"],
            record_kind="unit",
            unit_id=units[0].unit_id,
        )
        assert (
            record.outcome == "partial_source_preserved" and record.rows_preserved == 1
        )
        assert s.get(Raw, (CODE, date(2026, 6, 12), "week")).close_qfq == Decimal("10")


def test_current_market_incomplete_has_no_receipt_or_closure(db, monkeypatch):
    seed_frontier(db)
    definition, req, units = planned(
        db, requested(mode="point", trigger="schedule", code=None)
    )
    with pytest.raises(IngestionWriteError, match="本周源代码不完整"):
        execute(db, monkeypatch, definition, req, units, fake_pages(lambda _: []))
    with Session(db) as s:
        assert (
            s.scalar(select(Delivery.revision).where(Delivery.record_kind == "unit"))
            is None
        )
        assert (
            s.scalar(
                select(Delivery.revision).where(Delivery.record_kind == "batch_closed")
            )
            is None
        )


def test_duplicate_key_different_values_never_commits(db, monkeypatch):
    definition, req, units = planned(db)
    with pytest.raises(IngestionWriteError) as caught:
        execute(
            db,
            monkeypatch,
            definition,
            req,
            units,
            fake_pages(lambda _: [row(), row(qfq="6")]),
        )
    assert caught.value.structured_error.error_code == "weekly_adj.source_key_conflict"


def test_manual_revision_never_advances_automatic_frontier(db, monkeypatch):
    seed_frontier(db)
    definition, req, units = planned(db)
    execute(db, monkeypatch, definition, req, units, fake_pages(lambda _: [row()]))
    _, auto, auto_units = planned(
        db, requested(mode="point", trigger="schedule", code=None)
    )
    assert (
        auto_units[0].trade_date == WEEK
        and auto.execution_context["intent"] == "scheduled_week"
    )


def test_global_manual_history_after_bootstrap_keeps_replayable_rows(db, monkeypatch):
    seed_frontier(db)
    with Session(db) as session:
        for n in range(4):
            day = OLD - timedelta(days=4 - n)
            session.add(Daily(ts_code=CODE, trade_date=day, source="tushare"))
        session.commit()
    definition, req, units = planned(db, requested(end=OLD, code=None))
    assert req.execution_context["intent"] == "historical_refresh"
    assert not req.execution_context["business_plan"]["metadata"]["bootstrap"]
    execute(db, monkeypatch, definition, req, units, fake_pages(lambda _: [row()]))
    with Session(db) as session:
        receipt = StockWeeklyAdjDeliveryDAO(session).get_record(
            batch_id=req.execution_context["execution_token"],
            record_kind="unit",
            unit_id=units[0].unit_id,
        )
        assert receipt.intent["bootstrap"] is False
        assert receipt.payload["rows"][0]["close_qfq"] == "5.0000"


def test_unit_deadline_is_cumulative_and_uncommitted_raw_rolls_back(db, monkeypatch):
    from src.foundation.ingestion.stock_weekly_adj_execution import (
        bounded_unit_transaction,
    )

    clock = [0.0]
    monkeypatch.setattr(
        "src.foundation.ingestion.stock_weekly_adj_execution.time",
        SimpleNamespace(monotonic=lambda: clock[0]),
    )
    policy = weekly_definition().planning.weekly_adj_policy
    with pytest.raises(WeeklyAdjContractError) as caught:
        with Session(db) as session:
            with bounded_unit_transaction(session, policy, lambda: None) as ensure:
                session.add(Raw(**row(WEEK, close="20", qfq="20")))
                session.flush()
                clock[0] = policy.db_statement_timeout_seconds + 1
                ensure()
                session.commit()
    assert caught.value.code == "weekly_adj.business_deadline_exceeded"
    with Session(db) as session:
        assert session.get(Raw, (CODE, WEEK, "week")) is None


def test_queued_automatic_continuation_keeps_old_range_intent(db, monkeypatch):
    definition, req, units = planned(db)
    with pytest.raises(SystemExit):
        execute(
            db,
            monkeypatch,
            definition,
            req,
            units,
            fake_pages(lambda _: [], failure=SystemExit()),
        )
    with Session(db) as s:
        automatic, expected = resolve_weekly_adj_units(
            s,
            requested(mode="point", trigger="schedule", code=None),
            definition,
            now=NOW,
        )
    monkeypatch.setattr(
        "src.foundation.ingestion.resolver.get_dataset_definition", lambda _: definition
    )
    with Session(db) as s:
        queued = DatasetActionResolver(s).build_plan(
            DatasetActionRequest(
                definition.dataset_key,
                "maintain",
                DatasetTimeInput("point", trade_date=WEEK),
                trigger_source="schedule",
                execution_context=automatic.execution_context,
            )
        )
    assert (
        queued.execution_context["intent"] == "manual_revision"
        and queued.units == expected
    )
    assert queued.run_profile == "range_rebuild"


def test_business_scope_budget_is_checked_before_capture(db):
    definition = weekly_definition()
    definition = replace(
        definition,
        planning=replace(
            definition.planning,
            weekly_adj_policy=replace(
                definition.planning.weekly_adj_policy, max_batch_payload_bytes=1
            ),
        ),
    )
    req = requested()
    # Freeze this exact local budget, rather than spoofing a resume.
    ctx = freeze_weekly_adj_execution(
        definition,
        scope={"mode": "range", "start": OLD.isoformat(), "end": WEEK.isoformat()},
        filters={"ts_code": CODE},
        trigger_source="manual",
    )
    with Session(db) as s, pytest.raises(WeeklyAdjContractError, match="整批"):
        resolve_weekly_adj_units(
            s, replace(req, execution_context=ctx), definition, now=NOW
        )


def test_progress_projection_is_backend_owned_and_eta_unavailable():
    from src.ops.queries.task_run_query_service import TaskRunQueryService

    diagnostics = {
        "runtime": {
            "weekly_adj": {
                "stage": "刷新股票历史",
                "updated_at": "2026-10-10T00:00:00Z",
                "ts_code": CODE,
                "start_date": "20100101",
                "end_date": "20261009",
                "unit_done": 1,
                "unit_total": 2,
                "counters": {"preserved": 3},
            }
        }
    }
    projected = TaskRunQueryService._weekly_adj_progress(diagnostics)
    assert (
        projected.stage == "刷新股票历史"
        and projected.rows_preserved == 3
        and projected.eta == "unavailable"
    )
    assert TaskRunQueryService._weekly_adj_progress({}) is None
    assert (
        TaskRunQueryService._weekly_adj_progress(
            {"runtime": {"weekly_adj": {"unit_done": -1}}}
        )
        is None
    )


def test_cancel_after_commit_keeps_unit_and_does_not_close_or_claim_rollback(
    db, monkeypatch
):
    definition, req, units = planned(db)
    stopped = [False]

    def progress(snap, message):
        if snap.unit_done == 1:
            stopped[0] = True

    with pytest.raises(IngestionCanceledError):
        execute(
            db,
            monkeypatch,
            definition,
            req,
            units,
            fake_pages(lambda _: [row()]),
            cancel=lambda _: stopped[0],
            progress=progress,
        )
    with Session(db) as s:
        assert s.get(Raw, (CODE, OLD, "week")).close_qfq == Decimal("5")
        assert (
            s.scalar(select(Delivery.revision).where(Delivery.record_kind == "unit"))
            is not None
        )
        assert (
            s.scalar(
                select(Delivery.revision).where(Delivery.record_kind == "batch_closed")
            )
            is None
        )
    execute(
        db,
        monkeypatch,
        definition,
        req,
        units,
        fake_pages(
            lambda _: (_ for _ in ()).throw(AssertionError("receipt must skip source"))
        ),
    )


def test_serving_readback_mismatch_rolls_back_raw_and_receipt(db, monkeypatch):
    definition, req, units = planned(db)
    monkeypatch.setattr(
        "src.foundation.dao.stk_period_bar_adj_dao.StkPeriodBarAdjDAO.bulk_upsert",
        lambda self, rows, **_: len(rows),
    )
    with pytest.raises(IngestionWriteError, match="同事务读回"):
        execute(db, monkeypatch, definition, req, units, fake_pages(lambda _: [row()]))
    with Session(db) as s:
        assert s.get(Raw, (CODE, OLD, "week")).close_qfq == Decimal("10")
        assert (
            s.scalar(select(Delivery.revision).where(Delivery.record_kind == "unit"))
            is None
        )


def test_no_trading_week_closes_without_inventing_bars(db, monkeypatch):
    with Session(db) as s:
        for n in range(5, 10):
            s.get(Calendar, ("SSE", date(2026, 10, n))).is_open = False
        s.commit()
    seed_frontier(db)
    definition, req, units = planned(
        db, requested(mode="point", trigger="schedule", code=None)
    )
    assert len(units) == 1 and units[0].progress_context["no_trading_week"]

    def unexpected_source(**kwargs):
        pytest.fail("无交易周不得请求源数据")

    result = execute(db, monkeypatch, definition, req, units, unexpected_source)
    assert result.rows_written == 0 and result.unit_done == 1
    with Session(db) as s:
        record = StockWeeklyAdjDeliveryDAO(s).get_record(
            batch_id=req.execution_context["execution_token"],
            record_kind="unit",
            unit_id=units[0].unit_id,
        )
        assert record.outcome == "no_trading_week" and record.payload == {"rows": []}


def test_current_bootstrap_week_rejects_null_qfq_before_any_write(db, monkeypatch):
    definition, req, units = planned(db, requested(code=None))
    assert req.execution_context["business_plan"]["metadata"]["bootstrap"]
    current = next(unit for unit in units if unit.trade_date == WEEK)
    bad = {**row(WEEK, close="20", qfq="20"), "open_qfq": None}
    from src.foundation.ingestion.normalizer import NormalizedBatch
    from src.foundation.ingestion.writer import DatasetWriter

    with Session(db) as session:
        with pytest.raises(WeeklyAdjContractError, match="缺少前复权核心值"):
            DatasetWriter(session).write(
                definition=definition,
                batch=NormalizedBatch(
                    unit_id=current.unit_id,
                    rows_normalized=[bad],
                    rows_rejected=0,
                    rejected_reasons={},
                ),
                plan_unit=current,
                delivery_context=req.execution_context,
                cancel_check=lambda: None,
            )
        session.rollback()
        assert session.get(Raw, (CODE, WEEK, "week")) is None


def test_old_bootstrap_week_can_preserve_keys_without_daily_market_gate(db):
    from src.foundation.ingestion.normalizer import NormalizedBatch
    from src.foundation.ingestion.writer import DatasetWriter

    definition, req, units = planned(db, requested(code=None))
    old = next(unit for unit in units if unit.trade_date == OLD)
    assert not old.progress_context["require_complete_source"]
    with Session(db) as session:
        result = DatasetWriter(session).write(
            definition=definition,
            batch=NormalizedBatch(
                unit_id=old.unit_id,
                rows_normalized=[],
                rows_rejected=0,
                rejected_reasons={},
            ),
            plan_unit=old,
            delivery_context=req.execution_context,
            cancel_check=lambda: None,
        )
        session.commit()
        assert result.rows_written == 0
        assert result.persistence_diagnostics["weekly_adj"]["rows_preserved"] == 1
        assert session.get(Raw, (CODE, OLD, "week")).close_qfq == Decimal("10")


def test_future_week_and_wrong_scope_resume_rejected(db):
    with Session(db) as s, pytest.raises(WeeklyAdjContractError, match="尚未结束"):
        resolve_weekly_adj_units(
            s,
            requested(mode="point", end=date(2026, 10, 16)),
            weekly_definition(),
            now=NOW,
        )
    definition, req, units = planned(db)
    with pytest.raises(WeeklyAdjContractError, match="恢复范围"):
        requested(previous=req.execution_context, trigger="retry", code="600018.SH")
