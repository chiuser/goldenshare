from __future__ import annotations

from collections.abc import Generator
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.foundation.models.core.equity_block_trade import EquityBlockTrade
from src.ops.models.ops.sync_job_state import SyncJobState
from src.operations.services import SyncJobStateReconciliationService


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS core")
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS ops")
        EquityBlockTrade.__table__.create(connection)
        SyncJobState.__table__.create(connection)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = testing_session_local()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_preview_stale_sync_job_states_uses_observed_target_table_date(db_session: Session) -> None:
    db_session.add(
        EquityBlockTrade(
            ts_code="000001.SZ",
            trade_date=date(2026, 3, 26),
            buyer="buyer",
            seller="seller",
            price=10,
            vol=100,
            amount=1000,
        )
    )
    db_session.add(
        SyncJobState(
            job_name="sync_block_trade",
            target_table="core.equity_block_trade",
            last_success_date=date(2025, 12, 31),
            last_success_at=datetime(2026, 3, 29, tzinfo=timezone.utc),
            full_sync_done=False,
        )
    )
    db_session.commit()

    items = SyncJobStateReconciliationService().preview_stale_sync_job_states(db_session)

    assert [(item.job_name, item.previous_last_success_date, item.observed_last_success_date) for item in items] == [
        ("sync_block_trade", date(2025, 12, 31), date(2026, 3, 26)),
    ]


def test_reconcile_stale_sync_job_states_updates_only_outdated_rows(db_session: Session) -> None:
    db_session.add_all(
        [
            EquityBlockTrade(
                ts_code="000001.SZ",
                trade_date=date(2026, 3, 26),
                buyer="buyer",
                seller="seller",
                price=10,
                vol=100,
                amount=1000,
            ),
            SyncJobState(
                job_name="sync_block_trade",
                target_table="core.equity_block_trade",
                last_success_date=date(2025, 12, 31),
                last_success_at=datetime(2026, 3, 29, tzinfo=timezone.utc),
                full_sync_done=False,
            ),
        ]
    )
    db_session.commit()

    reconciled = SyncJobStateReconciliationService().reconcile_stale_sync_job_states(db_session)

    state = db_session.get(SyncJobState, "sync_block_trade")
    assert reconciled[0].job_name == "sync_block_trade"
    assert state is not None
    assert state.last_success_date == date(2026, 3, 26)
    assert state.last_success_at is not None
    assert state.last_success_at.date() == date(2026, 3, 29)
