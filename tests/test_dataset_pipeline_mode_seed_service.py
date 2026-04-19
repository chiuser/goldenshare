from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.ops.services.operations_dataset_pipeline_mode_seed_service import DatasetPipelineModeSeedService
from src.ops.specs.dataset_freshness_spec import DatasetFreshnessSpec
from src.ops.models.ops.dataset_pipeline_mode import DatasetPipelineMode


def _fake_specs() -> list[DatasetFreshnessSpec]:
    return [
        DatasetFreshnessSpec(
            dataset_key="stock_basic",
            resource_key="stock_basic",
            job_name="sync_stock_basic",
            display_name="股票主数据",
            domain_key="reference",
            domain_display_name="基础主数据",
            target_table="core_serving.security_serving",
            raw_table="raw_tushare.stock_basic",
            cadence="reference",
        ),
        DatasetFreshnessSpec(
            dataset_key="daily",
            resource_key="daily",
            job_name="sync_equity_daily",
            display_name="股票日线",
            domain_key="equity",
            domain_display_name="股票",
            target_table="core_serving.equity_daily_bar",
            raw_table="raw_tushare.daily",
            cadence="daily",
        ),
        DatasetFreshnessSpec(
            dataset_key="moneyflow",
            resource_key="moneyflow",
            job_name="sync_moneyflow",
            display_name="资金流",
            domain_key="equity",
            domain_display_name="股票",
            target_table="core_serving.equity_moneyflow",
            raw_table="raw_tushare.moneyflow",
            cadence="daily",
        ),
        DatasetFreshnessSpec(
            dataset_key="biying_equity_daily",
            resource_key="biying_equity_daily",
            job_name="sync_biying_equity_daily",
            display_name="BIYING 股票日线",
            domain_key="equity",
            domain_display_name="股票",
            target_table="raw_biying.equity_daily_bar",
            raw_table="raw_biying.equity_daily_bar",
            cadence="daily",
        ),
        DatasetFreshnessSpec(
            dataset_key="adj_factor",
            resource_key="adj_factor",
            job_name="sync_adj_factor",
            display_name="复权因子",
            domain_key="equity",
            domain_display_name="股票",
            target_table="core.equity_adj_factor",
            raw_table="raw_tushare.adj_factor",
            cadence="daily",
        ),
    ]


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
        DatasetPipelineMode.__table__.create(connection)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = testing_session_local()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_seed_dataset_pipeline_mode_apply(monkeypatch, db_session: Session) -> None:
    monkeypatch.setattr("src.ops.services.operations_dataset_pipeline_mode_seed_service.list_dataset_freshness_specs", _fake_specs)
    report = DatasetPipelineModeSeedService().run(db_session, dry_run=False)
    assert report.dataset_total == 5
    assert report.created == 5

    stock_basic = db_session.get(DatasetPipelineMode, "stock_basic")
    assert stock_basic is not None
    assert stock_basic.mode == "multi_source_pipeline"
    assert stock_basic.source_scope == "tushare,biying"

    daily = db_session.get(DatasetPipelineMode, "daily")
    assert daily is not None
    assert daily.mode == "single_source_direct"

    moneyflow = db_session.get(DatasetPipelineMode, "moneyflow")
    assert moneyflow is not None
    assert moneyflow.mode == "multi_source_pipeline"
    assert moneyflow.source_scope == "tushare,biying"

    biying_daily = db_session.get(DatasetPipelineMode, "biying_equity_daily")
    assert biying_daily is not None
    assert biying_daily.mode == "raw_only"

    adj_factor = db_session.get(DatasetPipelineMode, "adj_factor")
    assert adj_factor is not None
    assert adj_factor.mode == "legacy_core_direct"


def test_seed_dataset_pipeline_mode_dry_run(monkeypatch, db_session: Session) -> None:
    monkeypatch.setattr("src.ops.services.operations_dataset_pipeline_mode_seed_service.list_dataset_freshness_specs", _fake_specs)
    report = DatasetPipelineModeSeedService().run(db_session, dry_run=True)
    assert report.created == 5
    assert db_session.get(DatasetPipelineMode, "stock_basic") is None
