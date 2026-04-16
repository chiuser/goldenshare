from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.foundation.models.meta.dataset_resolution_policy import DatasetResolutionPolicy
from src.foundation.models.meta.dataset_source_status import DatasetSourceStatus
from src.operations.services.moneyflow_multi_source_seed_service import MoneyflowMultiSourceSeedService
from src.ops.models.ops.dataset_pipeline_mode import DatasetPipelineMode
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
        DatasetPipelineMode.__table__.create(connection)
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


def test_moneyflow_multi_source_seed_apply_is_idempotent(db_session: Session) -> None:
    service = MoneyflowMultiSourceSeedService()

    first = service.run(db_session, dry_run=False)
    assert first.dataset_key == "moneyflow"
    assert first.created_pipeline_mode == 1
    assert first.created_mapping_rules == 2
    assert first.created_cleansing_rules == 2
    assert first.created_source_statuses == 2
    assert first.created_resolution_policy == 1
    assert first.updated_resolution_policy == 0

    second = service.run(db_session, dry_run=False)
    assert second.created_pipeline_mode == 0
    assert second.updated_pipeline_mode == 0
    assert second.created_mapping_rules == 0
    assert second.created_cleansing_rules == 0
    assert second.created_source_statuses == 0
    assert second.created_resolution_policy == 0
    assert second.updated_resolution_policy == 0


def test_moneyflow_multi_source_seed_upgrades_single_source_defaults(db_session: Session) -> None:
    db_session.add(
        DatasetPipelineMode(
            dataset_key="moneyflow",
            mode="single_source_direct",
            source_scope="tushare",
            raw_enabled=True,
            std_enabled=False,
            resolution_enabled=False,
            serving_enabled=True,
            notes="legacy",
        )
    )
    db_session.add(
        DatasetResolutionPolicy(
            dataset_key="moneyflow",
            mode="primary_fallback",
            primary_source_key="tushare",
            fallback_source_keys=[],
            field_rules_json={},
            version=1,
            enabled=True,
        )
    )
    db_session.commit()

    report = MoneyflowMultiSourceSeedService().run(db_session, dry_run=False)
    assert report.updated_pipeline_mode == 1
    assert report.updated_resolution_policy == 1

    mode = db_session.get(DatasetPipelineMode, "moneyflow")
    assert mode is not None
    assert mode.mode == "multi_source_pipeline"
    assert mode.source_scope == "tushare,biying"
    assert mode.std_enabled is True
    assert mode.resolution_enabled is True

    policy = db_session.get(DatasetResolutionPolicy, "moneyflow")
    assert policy is not None
    assert tuple(policy.fallback_source_keys) == ("biying",)
    assert policy.version == 2
