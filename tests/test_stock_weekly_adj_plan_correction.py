"""Frozen-plan correction: producer schema and literal targets from LLD 11.1."""

from decimal import Decimal
from copy import deepcopy
from uuid import UUID
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.datasets.stock_weekly_adj_contracts import (
    SOURCE_FIELDS,
    WeeklyAdjContractError,
    canonical_source_rows,
    digest,
)
from src.foundation.ingestion.errors import IngestionWriteError
from src.foundation.ingestion.stock_weekly_adj_planning import restore_units
from src.foundation.ingestion.stock_weekly_adj_plan_correction import (
    build_correction_plan,
    apply_correction_plan,
    plan_record,
    receipt_headers,
)
from test_stock_weekly_adj_p2 import (
    CODE,
    OLD,
    WEEK,
    Daily,
    Factor,
    Raw,
    Delivery,
    execute,
    fake_pages,
    planned,
    requested,
    seed_frontier,
    isolated_lock,
    row,
    weekly_definition,
    load_changed_codes,
    db as sqlite_db,
)


@pytest.fixture
def db(tmp_path):
    yield from sqlite_db.__wrapped__(tmp_path)


"""Frozen-plan correction regression. Literal basis from Prod 17596/MCP, LLD 11.1."""


def test_target_uses_last_actual_trade_not_later_factor(db):
    # Same shape as 301139.SZ: trading stops Tuesday, later factors still change.
    with Session(db) as session:
        code = "301139.SZ"
        session.add_all(
            [
                Raw(**row(code=code)),
                Daily(ts_code=code, trade_date=date(2026, 10, 6), source="tushare"),
                Factor(
                    ts_code=code,
                    trade_date=date(2026, 10, 2),
                    adj_factor=Decimal("1.0079"),
                ),
                Factor(
                    ts_code=code,
                    trade_date=date(2026, 10, 5),
                    adj_factor=Decimal("1.0079"),
                ),
                Factor(
                    ts_code=code,
                    trade_date=date(2026, 10, 6),
                    adj_factor=Decimal("1.0079"),
                ),
                *[
                    Factor(
                        ts_code=code,
                        trade_date=date(2026, 10, n),
                        adj_factor=Decimal("1.1319"),
                    )
                    for n in (7, 8, 9)
                ],
            ]
        )
        session.commit()
        changes, *_ = load_changed_codes(
            session, WEEK, weekly_definition().planning.weekly_adj_policy
        )
        assert changes[code][1] == Decimal("1.0079")


def evidence(definition):
    # Producer schema: doc365 and Prod 17596 21 columns; literal independently known basis.
    rows = canonical_source_rows(
        [row(date(2026, 10, 2)), row(WEEK, close="20", qfq="20")],
        definition.planning.weekly_adj_policy,
    )
    assert rows[0]["close_qfq"] == "5.0000" and rows[1]["close_qfq"] == "20.0000"
    return dict(
        observed_at=datetime(2026, 10, 10, tzinfo=UTC).isoformat(),
        rows=rows,
        requests=[
            dict(
                api_name="stk_week_month_adj",
                fields=list(SOURCE_FIELDS),
                params=dict(
                    ts_code=CODE, freq="week", trade_date=day, limit=6000, offset=0
                ),
            )
            for day in ("20261002", "20261009")
        ],
    )


def broken_batch(db, monkeypatch):
    seed_frontier(db)
    definition, req, units = planned(
        db, requested(mode="point", trigger="schedule", code=None)
    )
    payload = deepcopy(req.execution_context["business_plan"])
    assert len(units) == 2
    payload["units"][1]["progress"]["factor_target"] = "3.00000000"
    payload["units"][1]["progress"].pop("factor_target_date", None)
    req = replace(
        req, execution_context={**req.execution_context, "business_plan": payload}
    )
    units = restore_units(payload, definition)
    with pytest.raises(IngestionWriteError, match="冻结计划不同"):
        execute(
            db,
            monkeypatch,
            definition,
            req,
            units,
            fake_pages(
                lambda u: [row(WEEK, close="20", qfq="20")] if u.trade_date else [row()]
            ),
        )
    with Session(db) as s:
        approved = build_correction_plan(
            s,
            definition,
            batch_id=req.execution_context["execution_token"],
            source_task_run_id=17596,
            source_evidence=evidence(definition),
            base_units=units,
        )
        original = deepcopy(
            plan_record(
                s, approved["batch_id"], definition.planning.weekly_adj_policy
            ).payload
        )
    return definition, req, units, approved, original


def apply(db, monkeypatch, definition, approved, **kwargs):
    monkeypatch.setattr(
        "src.foundation.ingestion.stock_weekly_adj_execution.publisher_lock",
        isolated_lock,
    )
    return apply_correction_plan(
        db,
        definition,
        approved,
        expected_digest=digest(approved),
        approval_ref="test/approved-17596",
        **kwargs,
    )


def test_correction_replay_and_original_batch_resume(db, monkeypatch):
    definition, req, units, approved, original = broken_batch(db, monkeypatch)
    assert approved["changes"][0]["old_factor_target"] == "3.00000000"
    assert approved["changes"][0]["new_factor_target"] == "2.00000000"
    assert len(approved["committed_units"]) == 1
    revision = apply(db, monkeypatch, definition, approved)
    assert apply(db, monkeypatch, definition, approved) == revision
    with Session(db) as s:
        effective = restore_units(original, definition, session=s)
    assert effective[1].progress_context["factor_target"] == "2.00000000"
    assert effective[1].unit_id == units[1].unit_id
    called = []

    def rows(u):
        called.append(u.unit_id)
        return [row(), row(WEEK, close="20", qfq="20")]

    result = execute(db, monkeypatch, definition, req, effective, fake_pages(rows))
    assert result.unit_done == 2 and called == [units[1].unit_id]
    # Re-applying after normal progress and closure must be harmless, too.
    assert apply(db, monkeypatch, definition, approved) == revision
    with Session(db) as s:
        assert (
            plan_record(
                s, approved["batch_id"], definition.planning.weekly_adj_policy
            ).payload
            == original
        )
        headers = receipt_headers(
            s, approved["batch_id"], definition.planning.weekly_adj_policy
        )
        assert headers[0] == approved["committed_units"][0]
        records = s.scalars(
            select(Delivery).where(
                Delivery.batch_id == UUID(req.execution_context["execution_token"])
            )
        ).all()
        assert sorted(r.record_kind for r in records) == [
            "batch_closed",
            "plan",
            "plan_correction",
            "unit",
            "unit",
        ]
        receipt = next(r for r in records if r.unit_id == units[1].unit_id)
        assert receipt.factor_target == Decimal("2")
        assert receipt.reason_summary["plan_correction_revision"] == revision


@pytest.mark.parametrize(
    "mutation",
    [
        "old_value",
        "scope",
        "unit",
        "params",
        "version",
        "digest",
        "future_date",
        "missing_check",
    ],
)
def test_invalid_approved_changes_never_write(db, monkeypatch, mutation):
    definition, _, _, approved, _ = broken_batch(db, monkeypatch)
    bad = deepcopy(approved)
    if mutation == "old_value":
        bad["changes"][0]["old_factor_target"] = "9.00000000"
    elif mutation == "scope":
        bad["scope_digest"] = "f" * 64
    elif mutation == "unit":
        bad["changes"][0]["unit_id"] = approved["committed_units"][0]["unit_id"]
    elif mutation == "params":
        bad["units"][1]["params"]["end_date"] = "20261016"
    elif mutation == "version":
        bad["correction_version"] = 2
    elif mutation == "digest":
        bad["original_plan_digest"] = "f" * 64
    elif mutation == "future_date":
        bad["changes"][0]["factor_target_date"] = "2026-10-16"
    else:
        bad["target_checks"] = []
    with pytest.raises(WeeklyAdjContractError):
        apply(db, monkeypatch, definition, bad)
    with Session(db) as s:
        assert (
            s.scalar(
                select(Delivery.revision).where(
                    Delivery.record_kind == "plan_correction"
                )
            )
            is None
        )


def test_changed_database_targets_require_new_review(db, monkeypatch):
    definition, _, _, approved, _ = broken_batch(db, monkeypatch)
    with Session(db) as s:
        s.get(Factor, (CODE, WEEK)).adj_factor = Decimal("4")
        s.commit()
    with pytest.raises(WeeklyAdjContractError):
        apply(db, monkeypatch, definition, approved)


def test_stale_worker_units_rejected_then_rebuild_succeeds(db, monkeypatch):
    definition, req, stale, approved, original = broken_batch(db, monkeypatch)
    apply(db, monkeypatch, definition, approved)
    called = []
    with pytest.raises(IngestionWriteError):
        execute(
            db,
            monkeypatch,
            definition,
            req,
            stale,
            fake_pages(lambda u: called.append(u)),
        )
    assert called == []
    # Resolver and the registered unit builder must both return the corrected value.
    from src.foundation.ingestion.resolver import DatasetActionResolver
    from src.foundation.ingestion.execution_plan import (
        DatasetActionRequest,
        DatasetTimeInput,
    )

    monkeypatch.setattr(
        "src.foundation.ingestion.resolver.get_dataset_definition", lambda _: definition
    )
    with Session(db) as s:
        plan = DatasetActionResolver(s).build_plan(
            DatasetActionRequest(
                definition.dataset_key,
                "maintain",
                DatasetTimeInput("point", trade_date=WEEK),
                trigger_source="retry",
                execution_context=req.execution_context,
            )
        )
        assert plan.units[1].progress_context["factor_target"] == "2.00000000"
        assert plan.execution_context["business_plan"] == original


@pytest.mark.parametrize("missing", ["daily", "factor"])
def test_missing_actual_day_coverage_rejected(db, missing):
    from src.foundation.ingestion.stock_weekly_adj_basis import (
        load_weekly_factor_targets,
    )

    with Session(db) as s:
        if missing == "daily":
            code = "999998.SZ"
            s.add(Factor(ts_code=code, trade_date=WEEK, adj_factor=Decimal("2")))
        else:
            code = "999997.SZ"
            s.add(Daily(ts_code=code, trade_date=OLD, source="tushare"))
            s.add(Factor(ts_code=code, trade_date=WEEK, adj_factor=Decimal("2")))
        s.commit()
        with pytest.raises(WeeklyAdjContractError, match="最后实际交易日"):
            load_weekly_factor_targets(s, [code], WEEK)


def test_cancel_corrected_unit_then_resume_retains_commits(db, monkeypatch):
    from src.foundation.ingestion.run_errors import IngestionCanceledError

    definition, req, _, approved, original = broken_batch(db, monkeypatch)
    apply(db, monkeypatch, definition, approved)
    with Session(db) as s:
        effective = restore_units(original, definition, session=s)
    state = {"cancel": False}
    with pytest.raises(IngestionCanceledError):
        execute(
            db,
            monkeypatch,
            definition,
            req,
            effective,
            fake_pages(lambda _: [row()], after_page=lambda: state.update(cancel=True)),
            cancel=lambda _: state["cancel"],
        )
    with Session(db) as s:
        assert (
            receipt_headers(
                s, approved["batch_id"], definition.planning.weekly_adj_policy
            )
            == approved["committed_units"]
        )
    state["cancel"] = False
    result = execute(
        db,
        monkeypatch,
        definition,
        req,
        effective,
        fake_pages(lambda _: [row()]),
        cancel=lambda _: state["cancel"],
    )
    assert result.unit_done == 2


def test_exit_after_correction_commit_and_after_unit_commit(db, monkeypatch):
    from sqlalchemy import event

    definition, req, _, approved, original = broken_batch(db, monkeypatch)
    state = {"committed": False}

    def committed(session):
        state["committed"] = True

    def check():
        if state["committed"]:
            raise SystemExit("exit after correction commit")

    event.listen(Session, "after_commit", committed)
    try:
        with pytest.raises(SystemExit):
            apply(db, monkeypatch, definition, approved, check=check)
    finally:
        event.remove(Session, "after_commit", committed)
    revision = apply(db, monkeypatch, definition, approved)
    with Session(db) as s:
        effective = restore_units(original, definition, session=s)

    def progress(snapshot, _message):
        if snapshot.unit_done == 2:
            raise SystemExit("exit after unit commit")

    with pytest.raises(SystemExit):
        execute(
            db,
            monkeypatch,
            definition,
            req,
            effective,
            fake_pages(lambda _: [row()]),
            progress=progress,
        )
    with Session(db) as s:
        effective = restore_units(original, definition, session=s)
    result = execute(
        db,
        monkeypatch,
        definition,
        req,
        effective,
        fake_pages(lambda _: pytest.fail("committed unit was downloaded again")),
    )
    assert result.unit_done == 2
    assert apply(db, monkeypatch, definition, approved) == revision


def test_later_trading_day_outside_cutoff_is_ignored(db):
    from src.foundation.ingestion.stock_weekly_adj_basis import (
        load_weekly_factor_targets,
    )

    with Session(db) as s:
        s.add(Daily(ts_code=CODE, trade_date=date(2026, 10, 16), source="tushare"))
        s.add(
            Factor(ts_code=CODE, trade_date=date(2026, 10, 16), adj_factor=Decimal("9"))
        )
        s.commit()
        assert load_weekly_factor_targets(s, [CODE], WEEK)[CODE] == (WEEK, Decimal("2"))


def test_cli_readonly_audit_atomic_file_and_explicit_apply(db, monkeypatch, tmp_path):
    import json
    from src.cli_parts.ingestion_handlers import run_weekly_adj_plan_correction
    from src.ops.models.ops.task_run import TaskRun
    from src.foundation.ingestion.source_client import DatasetSourceClient
    from sqlalchemy import event

    definition, req, _, approved, _ = broken_batch(db, monkeypatch)

    # This isolated SQLite DB has no Ops schema until the real producer model is attached.
    @event.listens_for(db, "connect")
    def attach_ops(conn, record):
        conn.execute(f"ATTACH DATABASE '{tmp_path}/ops.db' AS ops")

    db.dispose()
    TaskRun.__table__.create(db)
    with Session(db) as s:
        s.add(
            TaskRun(
                id=17596,
                task_type="dataset_action",
                resource_key=definition.dataset_key,
                action="maintain",
                title="test weekly",
                trigger_source="scheduled",
                status="failed",
                requested_at=datetime(2026, 10, 10, tzinfo=UTC),
                request_payload_json={"execution_context": req.execution_context},
            )
        )
        s.commit()
    monkeypatch.setattr(
        "src.foundation.datasets.registry.get_dataset_definition", lambda _: definition
    )
    expected = evidence(definition)
    # Only the external source is replaced. Builder, capture, normalize, DB audit are real.
    monkeypatch.setattr(
        DatasetSourceClient,
        "iter_weekly_adj_pages",
        staticmethod(
            fake_pages(
                lambda u: [
                    dict(r)
                    for r in expected["rows"]
                    if r["trade_date"] == u.request_params["trade_date"]
                ]
            )
        ),
    )
    statements = []

    def track(conn, cursor, statement, parameters, context, many):
        statements.append(statement.lstrip().split()[0].upper())

    event.listen(db, "before_cursor_execute", track)
    output = tmp_path / "approval.json"
    try:
        plan = run_weekly_adj_plan_correction(
            session_local=lambda: Session(db),
            task_run_id=17596,
            output=output,
            echo_fn=lambda _: None,
        )
        assert output.is_file() and json.loads(output.read_text()) == plan
        assert not {"INSERT", "UPDATE", "DELETE"}.intersection(statements)
    finally:
        event.remove(db, "before_cursor_execute", track)
    assert plan["changes"][0]["new_factor_target"] == "2.00000000"
    with pytest.raises(WeeklyAdjContractError, match="显式apply"):
        run_weekly_adj_plan_correction(
            session_local=lambda: pytest.fail("should not connect"),
            task_run_id=17596,
            output=output,
            approved_plan=output,
        )
    revision = run_weekly_adj_plan_correction(
        session_local=lambda: Session(db),
        task_run_id=17596,
        apply=True,
        approved_plan=output,
        expected_digest=digest(plan),
        approval_ref="CLI-reviewed",
        echo_fn=lambda _: None,
    )
    assert isinstance(revision, int)
    with Session(db) as s:
        assert s.get(TaskRun, 17596).status == "failed"
        assert (
            len(
                receipt_headers(
                    s, plan["batch_id"], definition.planning.weekly_adj_policy
                )
            )
            == 1
        )


def test_cli_entry_keeps_default_readonly(monkeypatch, tmp_path):
    from typer.testing import CliRunner
    import src.cli as cli

    calls = []
    monkeypatch.setattr(
        cli, "_run_weekly_adj_plan_correction_impl", lambda **kw: calls.append(kw)
    )
    result = CliRunner().invoke(
        cli.app,
        [
            "weekly-adj-plan-correction",
            "--task-run-id",
            "17596",
            "--output",
            str(tmp_path / "audit.json"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert calls[0]["apply"] is False and calls[0]["task_run_id"] == 17596


@pytest.mark.parametrize("value", ["0", "-1"])
def test_nonpositive_actual_day_factor_does_not_fall_forward(db, value):
    from src.foundation.ingestion.stock_weekly_adj_basis import (
        load_weekly_factor_targets,
    )

    with Session(db) as s:
        s.get(Factor, (CODE, WEEK)).adj_factor = Decimal(value)
        s.commit()
        with pytest.raises(WeeklyAdjContractError, match="有效因子"):
            load_weekly_factor_targets(s, [CODE], WEEK)


def test_corrected_empty_source_cannot_complete_unit(db, monkeypatch):
    definition, req, _, approved, original = broken_batch(db, monkeypatch)
    apply(db, monkeypatch, definition, approved)
    with Session(db) as s:
        units = restore_units(original, definition, session=s)
    with pytest.raises(IngestionWriteError, match="源历史变为空"):
        execute(db, monkeypatch, definition, req, units, fake_pages(lambda _: []))
    with Session(db) as s:
        assert (
            receipt_headers(
                s, approved["batch_id"], definition.planning.weekly_adj_policy
            )
            == approved["committed_units"]
        )


def test_first_apply_rejects_receipt_added_since_review(db, monkeypatch):
    from src.foundation.dao.stock_weekly_adj_delivery_dao import (
        StockWeeklyAdjDeliveryDAO,
    )
    from src.foundation.ingestion.stock_weekly_adj_delivery import delivery_record

    definition, req, units, approved, _ = broken_batch(db, monkeypatch)
    # Deliberate competing receipt only: this is not claimed to be a valid ingestion.
    rows = canonical_source_rows([row()], definition.planning.weekly_adj_policy)
    record = delivery_record(
        context=req.execution_context,
        kind="unit",
        unit_id=units[1].unit_id,
        unit=units[1],
        payload={"rows": rows},
        rows_received=1,
        rows_unique=1,
        rows_written=1,
    )
    with Session(db) as s:
        StockWeeklyAdjDeliveryDAO(s).append(
            record, definition.planning.weekly_adj_policy
        )
        s.commit()
    with pytest.raises(WeeklyAdjContractError, match="已经提交"):
        apply(db, monkeypatch, definition, approved)


def test_correction_sql_boundary_restores_full_128_blocks(db):
    from sqlalchemy import event
    from src.foundation.ingestion.stock_weekly_adj_basis import (
        load_weekly_factor_targets,
    )

    codes = [f"{800000 + n:06d}.SH" for n in range(257)]
    with Session(db) as s:
        for code in codes:
            s.add(Daily(ts_code=code, trade_date=OLD, source="tushare"))
            s.add(Factor(ts_code=code, trade_date=OLD, adj_factor=Decimal("1.0079")))
        s.commit()
    queries = []

    def sql(conn, cursor, statement, parameters, context, many):
        queries.append(statement)

    event.listen(db, "before_cursor_execute", sql)
    try:
        with Session(db) as s:
            targets = load_weekly_factor_targets(s, codes, WEEK)
    finally:
        event.remove(db, "before_cursor_execute", sql)
    assert len(targets) == 257 and all(
        v == (OLD, Decimal("1.0079")) for v in targets.values()
    )
    assert len(queries) == 6
    assert all("ORDER BY" in q and "LIMIT" in q for q in queries[::2])
