from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.runtime.ops_worker_factory import build_index_mins_worker, build_operations_worker, build_stk_mins_worker
from src.app.runtime.sector_heat_task_executor import SectorHeatTaskExecutor
from src.ops.runtime.maintenance_executor import MaintenanceExecutionUnit
from src.ops.runtime.worker_lane import WorkerLane


class _EmptyEvidenceProvider:
    def load(self, *, start_date, end_date):  # type: ignore[no-untyped-def]
        del start_date, end_date
        return ()


class _CommittingMaterializationStub:
    def materialize_trade_date(self, session, *, trade_date, **kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        session.execute(
            text("INSERT INTO transaction_probe (owner, trade_date) VALUES ('heat', :trade_date)"),
            {"trade_date": trade_date.isoformat()},
        )
        session.commit()
        return SimpleNamespace(
            rows_fetched=10,
            rows_written=2,
            invalid_count=1,
            valid_count=1,
            invalid_reason_counts={"FEATURE_MISSING": 1},
            elapsed_ms=5,
            config_hash="c" * 64,
            source_hash="s" * 64,
            plan_hash="p" * 64,
            content_hash="h" * 64,
            skipped_existing=False,
        )


def _session_factory():  # type: ignore[no-untyped-def]
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE transaction_probe ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL, trade_date TEXT NOT NULL)"
            )
        )
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_heat_business_commit_survives_later_ops_transaction_rollback() -> None:
    factory = _session_factory()
    executor = SectorHeatTaskExecutor(
        session_factory=factory,
        evidence_provider=_EmptyEvidenceProvider(),  # type: ignore[arg-type]
        materialization_service=_CommittingMaterializationStub(),  # type: ignore[arg-type]
    )
    ops_session = factory()
    result = executor.execute_unit(
        MaintenanceExecutionUnit(
            unit_key="wealth-sector-heat:2026-08-12",
            payload={"trade_date": "2026-08-12"},
        )
    )
    ops_session.execute(
        text("INSERT INTO transaction_probe (owner, trade_date) VALUES ('ops', '2026-08-12')")
    )
    ops_session.rollback()
    ops_session.close()

    with factory() as verification_session:
        owners = verification_session.scalars(
            select(text("owner")).select_from(text("transaction_probe")).order_by(text("id"))
        ).all()

    assert result.rows_saved == 2
    assert owners == ["heat"]


def test_worker_factory_reuses_one_existing_session_factory_and_registers_heat_executor() -> None:
    factory = _session_factory()

    worker = build_operations_worker(session_factory=factory)

    assert set(worker.dispatcher.maintenance_executors) == {"wealth_sector_heat", "news_stock_linking"}
    executor = worker.dispatcher.maintenance_executors["wealth_sector_heat"]
    assert isinstance(executor, SectorHeatTaskExecutor)
    assert executor._session_factory is factory


@pytest.mark.parametrize(
    ("factory", "lane"),
    [
        (build_operations_worker, WorkerLane.GENERAL),
        (build_stk_mins_worker, WorkerLane.STK_MINS),
        (build_index_mins_worker, WorkerLane.INDEX_MINS),
    ],
)
def test_worker_factories_share_dispatcher_assembly_and_select_lane(factory, lane) -> None:
    worker = factory(session_factory=_session_factory())

    assert worker.lane is lane
    assert set(worker.dispatcher.maintenance_executors) == {"wealth_sector_heat", "news_stock_linking"}
    assert isinstance(worker.dispatcher.maintenance_executors["wealth_sector_heat"], SectorHeatTaskExecutor)


def test_heat_business_transactions_use_repeatable_read_on_postgresql() -> None:
    session = MagicMock()
    session.get_bind.return_value.dialect.name = "postgresql"

    SectorHeatTaskExecutor._start_business_transaction(session, read_only=True)
    read_only_sql = str(session.execute.call_args.args[0])
    SectorHeatTaskExecutor._start_business_transaction(session, read_only=False)
    writable_sql = str(session.execute.call_args.args[0])

    assert read_only_sql == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
    assert writable_sql == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"
