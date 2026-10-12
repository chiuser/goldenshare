"""Two frozen first-history phases in isolated SQLite; no formal/source writes."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_stock_weekly_adj_p2 import (
    CODE,
    OLD,
    WEEK,
    execute,
    fake_pages,
    planned,
    requested,
    row,
)
from test_stock_weekly_adj_p2 import db as weekly_db

from src.foundation.datasets.stock_weekly_adj_contracts import WeeklyAdjContractError
from src.foundation.ingestion.errors import IngestionWriteError
from src.foundation.ingestion.run_errors import IngestionCanceledError
from src.foundation.ingestion.stock_weekly_adj_bootstrap import bootstrap_factor_scope
from src.foundation.ingestion.stock_weekly_adj_planning import (
    oldest_unclosed_plan,
    resolve_weekly_adj_units,
)
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

PREV = date(2026, 10, 2)
MONDAY = date(2026, 10, 12)
db = weekly_db


@pytest.fixture
def history(db, monkeypatch):
    with Session(db) as s:
        for model in (Raw, Serving):
            s.get(model, (CODE, OLD, "week")).trade_date = PREV
        s.commit()
    import src.foundation.ingestion.stock_weekly_adj_bootstrap as bootstrap

    actual = bootstrap.bootstrap_factor_scope
    monkeypatch.setattr(
        bootstrap,
        "bootstrap_factor_scope",
        lambda session, policy, **kwargs: actual(
            session,
            policy,
            today=MONDAY,
            **{k: v for k, v in kwargs.items() if k != "today"},
        ),
    )
    return db


def full_plan(history, previous=None):
    return planned(history, requested(start=PREV, code=None, previous=previous))


def pages(unit):
    return [
        row(
            unit.trade_date,
            close="10" if unit.trade_date == PREV else "20",
            qfq="5" if unit.trade_date == PREV else "20",
        )
    ]


def first(history, monkeypatch):
    definition, req, units = full_plan(history)
    assert req.execution_context["business_plan"]["metadata"]["bootstrap"]
    execute(history, monkeypatch, definition, req, units, fake_pages(pages))
    return definition, req, units


def change_factor(history):
    with Session(history) as s:
        s.add(Calendar(exchange="SSE", trade_date=MONDAY, is_open=True))
        s.add(Daily(ts_code=CODE, trade_date=MONDAY, source="tushare", close=20))
        s.add(Factor(ts_code=CODE, trade_date=MONDAY, adj_factor=4))
        s.commit()


def records(history, kind):
    with Session(history) as s:
        return list(
            s.scalars(
                select(Delivery)
                .where(Delivery.record_kind == kind)
                .order_by(Delivery.revision)
            )
        )


def no_source(**kwargs):
    pytest.fail("完成单元/零变化批不得重新下载")


def test_first_reconciles_then_independent_zero_request_boundary(history, monkeypatch):
    _, first_req, _ = first(history, monkeypatch)
    assert records(history, "bootstrap_closed") == []
    closed = records(history, "batch_closed")[0]
    assert closed.payload["bootstrap_reconciled"] is True
    definition, req, units = full_plan(history)
    assert units == ()
    meta = req.execution_context["business_plan"]["metadata"]
    assert (
        meta["bootstrap_parent_batch"] == first_req.execution_context["execution_token"]
    )
    execute(history, monkeypatch, definition, req, units, no_source)
    boundary = records(history, "bootstrap_closed")[0]
    assert boundary.payload["header"]["unit_count"] == 0
    assert boundary.payload["header"]["max_input_week"] is None
    assert boundary.payload["inventory"]["rows"] == 2
    assert boundary.payload["bootstrap_parent"]["revision"] == closed.revision
    assert boundary.batch_id != closed.batch_id
    definition, restored, restored_units = full_plan(history, req.execution_context)
    execute(history, monkeypatch, definition, restored, restored_units, no_source)
    assert len(records(history, "bootstrap_closed")) == 1
    with Session(history) as s:
        assert oldest_unclosed_plan(s) is None


def test_changed_factor_freezes_one_code_and_refreshes_history(history, monkeypatch):
    first(history, monkeypatch)
    change_factor(history)
    definition, req, units = full_plan(history)
    assert len(units) == 1 and units[0].trade_date is None
    assert units[0].request_params["ts_code"] == CODE
    assert units[0].progress_context["factor_target"] == "4.00000000"
    incoming = [
        row(PREV, qfq="2.5", basis=MONDAY),
        row(WEEK, close="20", qfq="10", basis=MONDAY),
    ]
    execute(
        history, monkeypatch, definition, req, units, fake_pages(lambda _: incoming)
    )
    assert len(records(history, "bootstrap_closed")) == 1
    with Session(history) as s:
        assert s.get(Raw, (CODE, PREV, "week")).close_qfq == Decimal("2.5")
        assert s.get(Raw, (CODE, OLD, "month")).close_qfq == Decimal(5)


def test_source_empty_changed_code_preserved_with_explicit_boundary_reason(
    history, monkeypatch
):
    first(history, monkeypatch)
    change_factor(history)
    definition, req, units = full_plan(history)
    execute(history, monkeypatch, definition, req, units, fake_pages(lambda _: []))
    boundary = records(history, "bootstrap_closed")[0]
    assert boundary.reason_summary["basis_audit"]["source_unavailable_codes"] == 1
    with Session(history) as s:
        assert s.get(Raw, (CODE, PREV, "week")).close_qfq == Decimal(5)


def test_cancel_during_first_audit_resumes_without_download(history, monkeypatch):
    definition, req, units = full_plan(history)
    cancelled = False

    def progress(snapshot, message):
        nonlocal cancelled
        cancelled |= "首次逐单元对账" in message

    with pytest.raises(IngestionCanceledError):
        execute(
            history,
            monkeypatch,
            definition,
            req,
            units,
            fake_pages(pages),
            progress=progress,
            cancel=lambda _: cancelled,
        )
    assert records(history, "batch_closed") == []
    assert (
        len([r for r in records(history, "unit") if not r.unit_id.startswith("audit:")])
        == 2
    )
    definition, restored, restored_units = full_plan(history, req.execution_context)
    execute(history, monkeypatch, definition, restored, restored_units, no_source)
    assert len(records(history, "batch_closed")) == 1


def test_first_audit_detects_modified_source_value(history, monkeypatch):
    definition, req, units = full_plan(history)
    cancelled = False

    def progress(snapshot, message):
        nonlocal cancelled
        cancelled |= "首次逐单元对账" in message

    with pytest.raises(IngestionCanceledError):
        execute(
            history,
            monkeypatch,
            definition,
            req,
            units,
            fake_pages(pages),
            progress=progress,
            cancel=lambda _: cancelled,
        )
    with Session(history) as s:
        s.get(Raw, (CODE, PREV, "week")).close_qfq = 999
        s.commit()
    definition, restored, restored_units = full_plan(history, req.execution_context)
    with pytest.raises(IngestionWriteError, match="对账不一致"):
        execute(history, monkeypatch, definition, restored, restored_units, no_source)
    assert records(history, "batch_closed") == []


def test_cancel_before_b0_keeps_catchup_plan_pending(history, monkeypatch):
    first(history, monkeypatch)
    definition, req, units = full_plan(history)
    cancelled = False

    def progress(snapshot, message):
        nonlocal cancelled
        cancelled |= "生成B0" in message

    with pytest.raises(IngestionCanceledError):
        execute(
            history,
            monkeypatch,
            definition,
            req,
            units,
            no_source,
            progress=progress,
            cancel=lambda _: cancelled,
        )
    assert len(records(history, "batch_closed")) == 2
    assert records(history, "bootstrap_closed") == []
    with Session(history) as s:
        assert (
            str(oldest_unclosed_plan(s).batch_id)
            == req.execution_context["execution_token"]
        )
    with pytest.raises(WeeklyAdjContractError, match="先续跑"):
        full_plan(history)
    definition, restored, restored_units = full_plan(history, req.execution_context)
    execute(history, monkeypatch, definition, restored, restored_units, no_source)
    assert len(records(history, "bootstrap_closed")) == 1


def test_new_factor_day_after_freeze_stops_b0(history, monkeypatch):
    first(history, monkeypatch)
    definition, req, units = full_plan(history)
    change_factor(history)
    with pytest.raises(IngestionWriteError, match="再次变化"):
        execute(history, monkeypatch, definition, req, units, no_source)
    assert records(history, "bootstrap_closed") == []


def test_same_day_factor_correction_after_freeze_stops_b0(history, monkeypatch):
    first(history, monkeypatch)
    definition, req, units = full_plan(history)
    with Session(history) as s:
        s.get(Factor, (CODE, WEEK)).adj_factor = 4
        s.commit()
    with pytest.raises(IngestionWriteError, match="再次变化"):
        execute(history, monkeypatch, definition, req, units, no_source)
    assert records(history, "bootstrap_closed") == []


def test_subset_never_becomes_closeout_and_post_b0_has_no_history_audit(
    history, monkeypatch
):
    first(history, monkeypatch)
    _, subset, _ = planned(history, requested(start=WEEK, code=None))
    assert subset.execution_context["business_plan"]["metadata"]["bootstrap"] is False
    definition, req, units = full_plan(history)
    execute(history, monkeypatch, definition, req, units, no_source)
    audit_count = len(
        [r for r in records(history, "unit") if r.unit_id.startswith("audit:")]
    )
    with Session(history) as s:
        s.get(Raw, (CODE, PREV, "week")).amount = 888
        s.commit()
    definition, daily_req, daily_units = planned(
        history, requested(mode="point", end=WEEK)
    )
    execute(history, monkeypatch, definition, daily_req, daily_units, fake_pages(pages))
    assert (
        len([r for r in records(history, "unit") if r.unit_id.startswith("audit:")])
        == audit_count
    )


def test_first_audit_detects_changed_preserved_serving_value(history, monkeypatch):
    definition, req, units = full_plan(history)
    cancelled = False

    def progress(snapshot, message):
        nonlocal cancelled
        cancelled |= "首次逐单元对账" in message

    with pytest.raises(IngestionCanceledError):
        execute(
            history,
            monkeypatch,
            definition,
            req,
            units,
            fake_pages(lambda u: [] if u.trade_date == PREV else pages(u)),
            progress=progress,
            cancel=lambda _: cancelled,
        )
    with Session(history) as s:
        s.get(Serving, (CODE, PREV, "week")).amount = 999
        s.commit()
    definition, restored, restored_units = full_plan(history, req.execution_context)
    with pytest.raises(IngestionWriteError, match="对账不一致"):
        execute(history, monkeypatch, definition, restored, restored_units, no_source)


def test_catchup_new_week_frozen_separately_and_requires_complete_source(
    history, monkeypatch
):
    first(history, monkeypatch)
    future = date(2026, 10, 16)
    with Session(history) as s:
        for n in range(12, 17):
            day = date(2026, 10, n)
            s.add(Calendar(exchange="SSE", trade_date=day, is_open=True))
            s.add(Daily(ts_code=CODE, trade_date=day, source="tushare", close=20))
            s.add(Factor(ts_code=CODE, trade_date=day, adj_factor=2))
        s.commit()
        definition = planned(history)[0]
        req, units = resolve_weekly_adj_units(
            s,
            requested(start=PREV, end=future, code=None),
            definition,
            now=datetime(2026, 10, 17, tzinfo=UTC),
        )
    assert len(units) == 1 and units[0].trade_date == future
    assert units[0].progress_context["require_complete_source"] is True
    assert units[0].progress_context["expected_codes_count"] == 1
    assert req.execution_context["business_plan"]["metadata"]["bootstrap_parent_batch"]


def test_new_listing_in_new_week_keeps_parent_target_scope(history, monkeypatch):
    first(history, monkeypatch)
    future = date(2026, 10, 16)
    code = "000002.SZ"
    with Session(history) as s:
        for n in range(12, 17):
            day = date(2026, 10, n)
            s.add(Calendar(exchange="SSE", trade_date=day, is_open=True))
            for c in (CODE, code):
                s.add(Daily(ts_code=c, trade_date=day, source="tushare", close=20))
                s.add(Factor(ts_code=c, trade_date=day, adj_factor=2))
        s.commit()
    monkeypatch.setattr(
        "src.foundation.ingestion.stock_weekly_adj_bootstrap.bootstrap_factor_scope",
        lambda session, policy, **kwargs: bootstrap_factor_scope(
            session,
            policy,
            today=date(2026, 10, 17),
            **{k: v for k, v in kwargs.items() if k != "today"},
        ),
    )
    definition = planned(history)[0]
    with Session(history) as s:
        req, units = resolve_weekly_adj_units(
            s,
            requested(start=PREV, end=future, code=None),
            definition,
            now=datetime(2026, 10, 17, tzinfo=UTC),
        )
    assert len(units) == 1 and units[0].progress_context["expected_codes_count"] == 2
    execute(
        history,
        monkeypatch,
        definition,
        req,
        units,
        fake_pages(
            lambda _: [
                row(future, c, close="20", qfq="20", basis=future) for c in (CODE, code)
            ]
        ),
    )
    assert records(history, "bootstrap_closed")[0].payload["inventory"]["rows"] == 4
