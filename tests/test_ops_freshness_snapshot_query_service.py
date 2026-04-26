from __future__ import annotations

from collections.abc import Generator
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.ops.dataset_definition_projection import list_dataset_freshness_projections
from src.ops.dataset_observation_registry import OBSERVED_DATE_MODEL_REGISTRY
from src.ops.models.ops.dataset_status_snapshot import DatasetStatusSnapshot
from src.ops.queries.freshness_query_service import OpsFreshnessQueryService


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
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = testing_session_local()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_build_from_snapshot_includes_raw_table_from_dataset_definition_projection(db_session: Session) -> None:
    db_session.add(
        DatasetStatusSnapshot(
            dataset_key="daily",
            resource_key="daily",
            display_name="股票日线",
            domain_key="equity",
            domain_display_name="股票",
            target_table="core.equity_daily_bar",
            cadence="daily",
            earliest_business_date=date(2026, 4, 1),
            observed_business_date=date(2026, 4, 1),
            latest_business_date=date(2026, 4, 1),
            freshness_note=None,
            latest_success_at=datetime(2026, 4, 1, 10, 0, tzinfo=timezone.utc),
            last_sync_date=date(2026, 4, 1),
            expected_business_date=date(2026, 4, 1),
            lag_days=0,
            freshness_status="fresh",
            recent_failure_message=None,
            recent_failure_summary=None,
            recent_failure_at=None,
            primary_action_key="daily.maintain",
            snapshot_date=date(2026, 4, 1),
            last_calculated_at=datetime(2026, 4, 1, 10, 1, tzinfo=timezone.utc),
        )
    )
    db_session.commit()

    response = OpsFreshnessQueryService._build_from_snapshot(db_session)

    assert response is not None
    item = response.groups[0].items[0]
    assert item.dataset_key == "daily"
    assert item.raw_table == "raw_tushare.daily"


def test_observed_model_registry_covers_equity_daily_business_date_tables() -> None:
    expected_tables = {
        "core_serving.equity_margin",
        "core_serving.equity_stk_limit",
        "core_serving.equity_stock_st",
        "core_serving.equity_nineturn",
        "core_serving.equity_suspend_d",
    }
    missing_tables = expected_tables - set(OBSERVED_DATE_MODEL_REGISTRY)
    assert not missing_tables


def test_all_observed_date_projections_have_model_mapping_and_column() -> None:
    missing_model: list[str] = []
    missing_column: list[str] = []
    for projection in list_dataset_freshness_projections():
        if not projection.observed_date_column:
            continue
        model = OBSERVED_DATE_MODEL_REGISTRY.get(projection.target_table)
        if model is None:
            missing_model.append(f"{projection.dataset_key}:{projection.target_table}")
            continue
        if not hasattr(model, projection.observed_date_column):
            missing_column.append(f"{projection.dataset_key}:{projection.target_table}.{projection.observed_date_column}")

    assert not missing_model
    assert not missing_column


def test_normalize_observed_date_accepts_month_key() -> None:
    assert OpsFreshnessQueryService._normalize_observed_date("202604") == date(2026, 4, 1)
