from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.foundation.models.meta.dataset_resolution_policy import DatasetResolutionPolicy
from src.foundation.models.meta.dataset_source_status import DatasetSourceStatus
from src.operations.services.default_single_source_seed_service import (
    DISABLED_DEFAULT_DATASET_KEYS,
    DefaultSingleSourceSeedService,
)
from src.operations.specs import list_dataset_freshness_specs
from src.ops.models.ops.std_cleansing_rule import StdCleansingRule
from src.ops.models.ops.std_mapping_rule import StdMappingRule


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
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS foundation")
        StdMappingRule.__table__.create(connection)
        StdCleansingRule.__table__.create(connection)
        DatasetResolutionPolicy.__table__.create(connection)
        DatasetSourceStatus.__table__.create(connection)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = testing_session_local()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _expected_tushare_dataset_count() -> int:
    return sum(
        1
        for spec in list_dataset_freshness_specs()
        if spec.dataset_key not in DISABLED_DEFAULT_DATASET_KEYS
        and spec.raw_table is not None
        and spec.raw_table.startswith("raw_tushare.")
    )


def test_seed_service_dry_run_reports_counts_without_writing(db_session: Session) -> None:
    report = DefaultSingleSourceSeedService().run(db_session, source_key="tushare", dry_run=True)

    assert report.dataset_total == _expected_tushare_dataset_count()
    assert report.created_mapping_rules == report.dataset_total
    assert report.created_cleansing_rules == report.dataset_total
    assert report.created_resolution_policies == report.dataset_total
    assert report.created_source_statuses == report.dataset_total

    assert db_session.scalar(select(func.count()).select_from(StdMappingRule)) == 0
    assert db_session.scalar(select(func.count()).select_from(StdCleansingRule)) == 0
    assert db_session.scalar(select(func.count()).select_from(DatasetResolutionPolicy)) == 0
    assert db_session.scalar(select(func.count()).select_from(DatasetSourceStatus)) == 0


def test_seed_service_apply_is_idempotent(db_session: Session) -> None:
    first = DefaultSingleSourceSeedService().run(db_session, source_key="tushare", dry_run=False)
    second = DefaultSingleSourceSeedService().run(db_session, source_key="tushare", dry_run=False)

    assert first.dataset_total == _expected_tushare_dataset_count()
    assert first.created_mapping_rules == first.dataset_total
    assert first.created_cleansing_rules == first.dataset_total
    assert first.created_resolution_policies == first.dataset_total
    assert first.created_source_statuses == first.dataset_total

    assert second.created_mapping_rules == 0
    assert second.created_cleansing_rules == 0
    assert second.created_resolution_policies == 0
    assert second.created_source_statuses == 0

    assert db_session.scalar(select(func.count()).select_from(StdMappingRule)) == first.dataset_total
    assert db_session.scalar(select(func.count()).select_from(StdCleansingRule)) == first.dataset_total
    assert db_session.scalar(select(func.count()).select_from(DatasetResolutionPolicy)) == first.dataset_total
    assert db_session.scalar(select(func.count()).select_from(DatasetSourceStatus)) == first.dataset_total
