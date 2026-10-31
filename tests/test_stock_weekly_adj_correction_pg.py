"""Real task-owned PostgreSQL migration, immutability, cancellation and recovery."""

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text, insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from src.foundation.datasets.stock_weekly_adj_contracts import digest
from src.foundation.ingestion.stock_weekly_adj_execution import (
    publisher_lock as real_lock,
)
from src.foundation.ingestion.stock_weekly_adj_plan_correction import (
    apply_correction_plan,
    receipt_headers,
)
from src.foundation.ingestion.stock_weekly_adj_delivery import delivery_record
from src.foundation.ingestion.stock_weekly_adj_planning import restore_units
from src.foundation.ingestion.run_errors import IngestionCanceledError
from test_stock_weekly_adj_pg import pg as owned_pg, migrate, run
from test_stock_weekly_adj_plan_correction import broken_batch
from test_stock_weekly_adj_p2 import Delivery, Raw, Serving, OLD, CODE, row, fake_pages


@pytest.fixture
def pg():
    yield from owned_pg.__wrapped__()


def test_pg_migration_correction_and_real_cancel_resume(pg, monkeypatch):
    migrate(pg, "20261031_000187")
    definition, req, _, approved, original = broken_batch(pg, monkeypatch)
    monkeypatch.setattr(
        "src.foundation.ingestion.stock_weekly_adj_execution.publisher_lock", real_lock
    )
    revision = apply_correction_plan(
        pg,
        definition,
        approved,
        expected_digest=digest(approved),
        approval_ref="pg-approved",
    )
    for verb in (
        "UPDATE core.stock_weekly_adj_delivery SET outcome=outcome",
        "DELETE FROM core.stock_weekly_adj_delivery",
    ):
        with pytest.raises(DBAPIError, match="append-only"):
            with pg.begin() as conn:
                conn.execute(text(verb))
    with Session(pg) as s:
        effective = restore_units(original, definition, session=s)
        assert (
            receipt_headers(
                s, approved["batch_id"], definition.planning.weekly_adj_policy
            )
            == approved["committed_units"]
        )
    state = {"cancel": False}
    with pytest.raises(IngestionCanceledError):
        run(
            pg,
            definition,
            req,
            effective,
            fake_pages(lambda _: [row()], after_page=lambda: state.update(cancel=True)),
            cancel_checker=lambda _: state["cancel"],
        )
    with Session(pg) as s:
        assert (
            len(
                receipt_headers(
                    s, approved["batch_id"], definition.planning.weekly_adj_policy
                )
            )
            == 1
        )
    result = run(pg, definition, req, effective, fake_pages(lambda _: [row()]))
    assert result.unit_done == 2
    with Session(pg) as s:
        stored = s.get(Raw, (CODE, OLD, "week"))
        served = s.get(Serving, (CODE, OLD, "week"))
        assert stored.close_qfq == served.close_qfq == Decimal("5")
        assert (
            len(
                receipt_headers(
                    s, approved["batch_id"], definition.planning.weekly_adj_policy
                )
            )
            == 2
        )
        assert (
            s.scalar(
                select(Delivery).where(
                    Delivery.batch_id == UUID(approved["batch_id"]),
                    Delivery.record_kind == "plan",
                )
            ).payload
            == original
        )
    assert (
        apply_correction_plan(
            pg,
            definition,
            approved,
            expected_digest=digest(approved),
            approval_ref="pg-approved",
        )
        == revision
    )
    # CHECK must reject an oversized correction even when the DAO is bypassed.
    context = {**original["execution_context"], "business_plan": original}
    bad = delivery_record(
        context=context,
        kind="plan_correction",
        unit_id="plan_correction",
        payload={"padding": "x" * 1048576},
    )
    bad["batch_id"] = uuid4()
    with pytest.raises(DBAPIError, match="ck_weekly_adj_correction_bytes"):
        with pg.begin() as conn:
            conn.execute(insert(Delivery).values(**bad))


def test_pg_cli_audit_uses_readonly_transaction(pg, monkeypatch, tmp_path):
    from datetime import UTC, datetime
    from sqlalchemy import event
    from src.cli_parts.ingestion_handlers import run_weekly_adj_plan_correction
    from src.foundation.ingestion.source_client import DatasetSourceClient
    from src.ops.models.ops.task_run import TaskRun
    from test_stock_weekly_adj_plan_correction import evidence

    migrate(pg, "20261031_000187")
    definition, req, _, _, _ = broken_batch(pg, monkeypatch)
    with Session(pg) as session:
        session.add(
            TaskRun(
                id=17596,
                task_type="dataset_action",
                resource_key=definition.dataset_key,
                action="maintain",
                title="isolated task",
                trigger_source="scheduled",
                status="failed",
                requested_at=datetime(2026, 10, 10, tzinfo=UTC),
                request_payload_json={"execution_context": req.execution_context},
            )
        )
        session.commit()
    monkeypatch.setattr(
        "src.foundation.datasets.registry.get_dataset_definition", lambda _: definition
    )
    active = []

    def factory():
        session = Session(pg)
        active.append(session)
        return session

    def attempt_write(**kwargs):
        # Deliberately wrong source adapter: the audit DB transaction must reject it.
        active[-1].execute(text("UPDATE ops.task_run SET title=title WHERE id=17596"))
        yield

    monkeypatch.setattr(
        DatasetSourceClient, "iter_weekly_adj_pages", staticmethod(attempt_write)
    )
    output = tmp_path / "audit.json"
    with pytest.raises(DBAPIError, match="read-only"):
        run_weekly_adj_plan_correction(
            session_local=factory,
            task_run_id=17596,
            output=output,
            echo_fn=lambda _: None,
        )
    assert not output.exists()
    rows = evidence(definition)["rows"]
    monkeypatch.setattr(
        DatasetSourceClient,
        "iter_weekly_adj_pages",
        staticmethod(
            fake_pages(
                lambda u: [
                    dict(r)
                    for r in rows
                    if r["trade_date"] == u.request_params["trade_date"]
                ]
            )
        ),
    )
    writes = []

    def sql(conn, cursor, statement, parameters, context, many):
        if (
            statement.lstrip()
            .upper()
            .startswith(("INSERT", "UPDATE", "DELETE", "ALTER"))
        ):
            writes.append(statement)

    event.listen(pg, "before_cursor_execute", sql)
    try:
        approved = run_weekly_adj_plan_correction(
            session_local=factory,
            task_run_id=17596,
            output=output,
            echo_fn=lambda _: None,
        )
    finally:
        event.remove(pg, "before_cursor_execute", sql)
    assert output.is_file() and not writes
    assert approved["changes"][0]["new_factor_target"] == "2.00000000"
