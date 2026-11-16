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
