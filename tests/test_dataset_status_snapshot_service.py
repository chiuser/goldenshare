from __future__ import annotations

from collections.abc import Generator
from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.ops.models.ops.dataset_layer_snapshot_history import DatasetLayerSnapshotHistory
from src.ops.models.ops.dataset_status_snapshot import DatasetStatusSnapshot
from src.operations.services.dataset_status_snapshot_service import DatasetStatusSnapshotService
from src.ops.schemas.freshness import DatasetFreshnessItem


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS ops")
        DatasetStatusSnapshot.__table__.create(connection)
        DatasetLayerSnapshotHistory.__table__.create(connection)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = testing_session_local()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


class FakeFreshnessQueryService:
    def build_live_items(self, session: Session, *, today: date | None = None, resource_keys: list[str] | None = None) -> list[DatasetFreshnessItem]:
        assert resource_keys == ["stock_basic"]
        return [
            DatasetFreshnessItem(
                dataset_key="stock_basic",
                resource_key="stock_basic",
                display_name="股票主数据",
                domain_key="reference_data",
                domain_display_name="基础主数据",
                job_name="sync_stock_basic",
                target_table="core.security_serving",
                cadence="reference",
                latest_business_date=None,
                freshness_status="fresh",
                last_sync_date=date(2026, 4, 1),
                full_sync_done=True,
            )
        ]


def test_refresh_resources_upserts_snapshot_rows(db_session: Session) -> None:
    service = DatasetStatusSnapshotService(query_service=FakeFreshnessQueryService())

    refreshed = service.refresh_resources(db_session, ["stock_basic"], today=date(2026, 4, 1))

    assert refreshed == 1
    row = db_session.scalar(select(DatasetStatusSnapshot).where(DatasetStatusSnapshot.dataset_key == "stock_basic"))
    assert row is not None
    assert row.display_name == "股票主数据"
    assert row.last_sync_date == date(2026, 4, 1)
    assert row.snapshot_date == date(2026, 4, 1)
