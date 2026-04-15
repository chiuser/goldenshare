from __future__ import annotations

from collections.abc import Generator
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.foundation.models.meta.dataset_resolution_policy import DatasetResolutionPolicy
from src.ops.models.ops.dataset_pipeline_mode import DatasetPipelineMode
from src.ops.models.ops.dataset_status_snapshot import DatasetStatusSnapshot
from src.ops.models.ops.std_cleansing_rule import StdCleansingRule
from src.ops.models.ops.std_mapping_rule import StdMappingRule
from src.ops.queries.dataset_pipeline_mode_query_service import DatasetPipelineModeQueryService


def _now() -> datetime:
    return datetime.now(timezone.utc)


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
        DatasetStatusSnapshot.__table__.create(connection)
        DatasetPipelineMode.__table__.create(connection)
        StdMappingRule.__table__.create(connection)
        StdCleansingRule.__table__.create(connection)
        DatasetResolutionPolicy.__table__.create(connection)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = testing_session_local()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_pipeline_mode_query_lists_mode_and_rule_status(db_session: Session) -> None:
    db_session.add_all(
        [
            DatasetStatusSnapshot(
                dataset_key="stock_basic",
                resource_key="stock_basic",
                display_name="股票主数据",
                domain_key="reference",
                domain_display_name="基础主数据",
                job_name="sync_stock_basic",
                target_table="core_serving.security_serving",
                cadence="reference",
                business_date_source="none",
                freshness_status="fresh",
                snapshot_date=date(2026, 4, 15),
                last_calculated_at=_now(),
            ),
            DatasetStatusSnapshot(
                dataset_key="daily",
                resource_key="daily",
                display_name="股票日线",
                domain_key="equity",
                domain_display_name="股票",
                job_name="sync_equity_daily",
                target_table="core_serving.equity_daily_bar",
                cadence="daily",
                latest_business_date=date(2026, 4, 15),
                business_date_source="observed",
                freshness_status="fresh",
                snapshot_date=date(2026, 4, 15),
                last_calculated_at=_now(),
            ),
            DatasetStatusSnapshot(
                dataset_key="block_trade",
                resource_key="block_trade",
                display_name="大宗交易",
                domain_key="equity",
                domain_display_name="股票",
                job_name="sync_block_trade",
                target_table="core.equity_block_trade",
                cadence="daily",
                latest_business_date=date(2026, 4, 15),
                business_date_source="observed",
                freshness_status="fresh",
                snapshot_date=date(2026, 4, 15),
                last_calculated_at=_now(),
            ),
            DatasetPipelineMode(
                dataset_key="stock_basic",
                mode="multi_source_pipeline",
                source_scope="tushare,biying",
                raw_enabled=True,
                std_enabled=True,
                resolution_enabled=True,
                serving_enabled=True,
            ),
            DatasetPipelineMode(
                dataset_key="daily",
                mode="single_source_direct",
                source_scope="tushare",
                raw_enabled=True,
                std_enabled=False,
                resolution_enabled=False,
                serving_enabled=True,
            ),
            StdMappingRule(
                dataset_key="stock_basic",
                source_key="tushare",
                src_field="*",
                std_field="*",
                src_type=None,
                std_type=None,
                transform_fn="identity_pass_through",
                lineage_preserved=True,
                status="active",
                rule_set_version=1,
            ),
            StdCleansingRule(
                dataset_key="stock_basic",
                source_key="tushare",
                rule_type="builtin_default",
                target_fields_json=[],
                condition_expr=None,
                action="pass_through",
                status="active",
                rule_set_version=1,
            ),
            DatasetResolutionPolicy(
                dataset_key="stock_basic",
                mode="primary_fallback",
                primary_source_key="tushare",
                fallback_source_keys=["biying"],
                field_rules_json={},
                version=1,
                enabled=True,
            ),
        ]
    )
    db_session.commit()

    result = DatasetPipelineModeQueryService().list_modes(db_session)
    assert result.total >= 3
    by_key = {item.dataset_key: item for item in result.items}

    stock_basic = by_key["stock_basic"]
    assert stock_basic.mode == "multi_source_pipeline"
    assert stock_basic.layer_plan == "raw->std->resolution->serving"
    assert stock_basic.std_mapping_configured is True
    assert stock_basic.std_cleansing_configured is True
    assert stock_basic.resolution_policy_configured is True
    assert stock_basic.std_table_hint == "core_multi.security_std"

    daily = by_key["daily"]
    assert daily.mode == "single_source_direct"
    assert daily.layer_plan == "raw->serving"
    assert daily.std_mapping_configured is False
    assert daily.resolution_policy_configured is False

    block_trade = by_key["block_trade"]
    assert block_trade.mode == "single_source_direct"
    assert block_trade.serving_table == "core_serving.equity_block_trade"


def test_pipeline_mode_query_includes_spec_even_without_snapshot(db_session: Session) -> None:
    db_session.add(
        DatasetPipelineMode(
            dataset_key="biying_moneyflow",
            mode="raw_only",
            source_scope="biying",
            raw_enabled=True,
            std_enabled=False,
            resolution_enabled=False,
            serving_enabled=False,
        )
    )
    db_session.commit()

    result = DatasetPipelineModeQueryService().list_modes(db_session)
    by_key = {item.dataset_key: item for item in result.items}

    assert "biying_moneyflow" in by_key
    item = by_key["biying_moneyflow"]
    assert item.mode == "raw_only"
    assert item.source_scope == "biying"
    assert item.raw_table == "raw_biying.moneyflow"
    assert item.freshness_status == "unknown"
