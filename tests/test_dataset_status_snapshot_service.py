from __future__ import annotations

from collections.abc import Generator
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.foundation.models.core_serving_light.equity_daily_bar_light import EquityDailyBarLight
from src.ops.models.ops.dataset_layer_snapshot_current import DatasetLayerSnapshotCurrent
from src.ops.models.ops.dataset_layer_snapshot_history import DatasetLayerSnapshotHistory
from src.ops.models.ops.dataset_status_snapshot import DatasetStatusSnapshot
from src.ops.services.operations_dataset_status_snapshot_service import DatasetStatusSnapshotService
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
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS core_serving_light")
        DatasetStatusSnapshot.__table__.create(connection)
        DatasetLayerSnapshotHistory.__table__.create(connection)
        DatasetLayerSnapshotCurrent.__table__.create(connection)
        EquityDailyBarLight.__table__.create(connection)
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
                target_table="core.security_serving",
                cadence="reference",
                latest_business_date=None,
                freshness_status="fresh",
                last_sync_date=date(2026, 4, 1),
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

    current_rows = list(
        db_session.scalars(
            select(DatasetLayerSnapshotCurrent).where(DatasetLayerSnapshotCurrent.dataset_key == "stock_basic")
        )
    )
    by_stage = {r.stage: r for r in current_rows}
    assert by_stage["raw"].status == "fresh"
    assert by_stage["serving"].status == "fresh"


def test_refresh_for_target_resolves_dataset_action_target_key(db_session: Session) -> None:
    class _MoneyflowFreshnessQueryService:
        def build_live_items(
            self,
            session: Session,
            *,
            today: date | None = None,
            resource_keys: list[str] | None = None,
        ) -> list[DatasetFreshnessItem]:
            assert resource_keys == ["moneyflow_ind_dc"]
            return [
                DatasetFreshnessItem(
                    dataset_key="moneyflow_ind_dc",
                    resource_key="moneyflow_ind_dc",
                    display_name="板块资金流向（东方财富）",
                    domain_key="moneyflow",
                    domain_display_name="资金流向",
                    target_table="core_serving.board_moneyflow_dc",
                    cadence="daily",
                    latest_business_date=date(2026, 4, 24),
                    freshness_status="fresh",
                    last_sync_date=date(2026, 4, 24),
                )
            ]

    service = DatasetStatusSnapshotService(query_service=_MoneyflowFreshnessQueryService())

    refreshed = service.refresh_for_target(
        db_session,
        target_type="dataset_action",
        target_key="moneyflow_ind_dc.maintain",
        today=date(2026, 4, 24),
        strict=True,
    )

    assert refreshed == 1
    row = db_session.scalar(select(DatasetStatusSnapshot).where(DatasetStatusSnapshot.dataset_key == "moneyflow_ind_dc"))
    assert row is not None
    assert row.latest_business_date == date(2026, 4, 24)
    assert row.freshness_status == "fresh"


def test_read_snapshot_restores_raw_table_from_registry(db_session: Session) -> None:
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
            latest_success_at=None,
            last_sync_date=date(2026, 4, 1),
            expected_business_date=date(2026, 4, 1),
            lag_days=0,
            freshness_status="fresh",
            recent_failure_message=None,
            recent_failure_summary=None,
            recent_failure_at=None,
            primary_action_key="daily.maintain",
            snapshot_date=date(2026, 4, 1),
            last_calculated_at=datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc),
        )
    )
    db_session.commit()

    response = DatasetStatusSnapshotService().read_snapshot(db_session)

    assert response is not None
    item = response.groups[0].items[0]
    assert item.dataset_key == "daily"
    assert item.raw_table == "raw_tushare.daily"


def test_refresh_resources_marks_enabled_layers_as_unobserved(db_session: Session) -> None:
    class _FakeQueryService:
        def build_live_items(self, session: Session, *, today: date | None = None, resource_keys: list[str] | None = None) -> list[DatasetFreshnessItem]:
            assert resource_keys == ["stock_basic"]
            return [
                DatasetFreshnessItem(
                    dataset_key="stock_basic",
                    resource_key="stock_basic",
                    display_name="股票主数据",
                    domain_key="reference_data",
                    domain_display_name="基础主数据",
                    target_table="core_serving.security_serving",
                    cadence="reference",
                    latest_business_date=date(2026, 4, 1),
                    freshness_status="fresh",
                    last_sync_date=date(2026, 4, 1),
                )
            ]

    service = DatasetStatusSnapshotService(query_service=_FakeQueryService())
    refreshed = service.refresh_resources(db_session, ["stock_basic"], today=date(2026, 4, 1))
    assert refreshed == 1

    rows = list(
        db_session.scalars(
            select(DatasetLayerSnapshotCurrent).where(DatasetLayerSnapshotCurrent.dataset_key == "stock_basic")
        )
    )
    by_stage = {row.stage: row for row in rows}
    assert by_stage["raw"].status == "fresh"
    assert by_stage["std"].status == "unobserved"
    assert by_stage["resolution"].status == "unobserved"
    assert by_stage["serving"].status == "fresh"


def test_refresh_resources_uses_runtime_health_for_not_applicable_dataset(db_session: Session) -> None:
    class _FakeQueryService:
        def build_live_items(self, session: Session, *, today: date | None = None, resource_keys: list[str] | None = None) -> list[DatasetFreshnessItem]:
            assert resource_keys == ["namechange"]
            return [
                DatasetFreshnessItem(
                    dataset_key="namechange",
                    resource_key="namechange",
                    display_name="股票曾用名",
                    domain_key="reference_data",
                    domain_display_name="基础主数据",
                    target_table="core_serving_light.namechange",
                    cadence="daily",
                    latest_business_date=date(2026, 4, 30),
                    freshness_status="unknown",
                    last_sync_date=date(2026, 5, 5),
                    latest_success_at=datetime(2026, 5, 5, 14, 0, tzinfo=timezone.utc),
                )
            ]

    service = DatasetStatusSnapshotService(query_service=_FakeQueryService())

    refreshed = service.refresh_resources(db_session, ["namechange"], today=date(2026, 5, 5))

    assert refreshed == 1
    rows = list(
        db_session.scalars(
            select(DatasetLayerSnapshotCurrent).where(DatasetLayerSnapshotCurrent.dataset_key == "namechange")
        )
    )
    by_stage = {row.stage: row for row in rows}
    assert by_stage["raw"].status == "healthy"
    assert by_stage["light"].status == "healthy"


def test_refresh_resources_keeps_combined_scope_current_rows(db_session: Session) -> None:
    class _FakeQueryService:
        def build_live_items(self, session: Session, *, today: date | None = None, resource_keys: list[str] | None = None) -> list[DatasetFreshnessItem]:
            assert resource_keys == ["stock_basic"]
            return [
                DatasetFreshnessItem(
                    dataset_key="stock_basic",
                    resource_key="stock_basic",
                    display_name="股票主数据",
                    domain_key="reference_data",
                    domain_display_name="基础主数据",
                    target_table="core_serving.security_serving",
                    cadence="reference",
                    latest_business_date=date(2026, 4, 1),
                    freshness_status="fresh",
                    last_sync_date=date(2026, 4, 1),
                )
            ]

    db_session.add(
        DatasetLayerSnapshotCurrent(
            dataset_key="stock_basic",
            source_key="combined",
            stage="raw",
            status="unknown",
            calculated_at=datetime(2026, 3, 31, 0, 0, tzinfo=timezone.utc),
        )
    )
    db_session.commit()

    service = DatasetStatusSnapshotService(query_service=_FakeQueryService())
    refreshed = service.refresh_resources(db_session, ["stock_basic"], today=date(2026, 4, 1))

    assert refreshed == 1
    rows = list(
        db_session.scalars(
            select(DatasetLayerSnapshotCurrent).where(DatasetLayerSnapshotCurrent.dataset_key == "stock_basic")
        )
    )
    assert {row.source_key for row in rows} == {"combined"}


def test_refresh_resources_writes_light_stage_snapshot_for_equity_daily(db_session: Session) -> None:
    class _FakeQueryService:
        def build_live_items(self, session: Session, *, today: date | None = None, resource_keys: list[str] | None = None) -> list[DatasetFreshnessItem]:
            assert resource_keys == ["daily"]
            return [
                DatasetFreshnessItem(
                    dataset_key="daily",
                    resource_key="daily",
                    display_name="股票日线",
                    domain_key="equity",
                    domain_display_name="股票",
                    target_table="core_serving.equity_daily_bar",
                    cadence="daily",
                    latest_business_date=date(2026, 4, 2),
                    freshness_status="fresh",
                    last_sync_date=date(2026, 4, 2),
                )
            ]

    db_session.add(
        EquityDailyBarLight(
            ts_code="000001.SZ",
            trade_date=date(2026, 4, 2),
            open=10.0,
            high=10.2,
            low=9.9,
            close=10.1,
            pre_close=10.0,
            change_amount=0.1,
            pct_chg=1.0,
            vol=1000.0,
            amount=100000.0,
            source="tushare",
            created_at=datetime(2026, 4, 2, 11, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 4, 2, 11, 0, tzinfo=timezone.utc),
        )
    )
    db_session.commit()

    service = DatasetStatusSnapshotService(query_service=_FakeQueryService())
    refreshed = service.refresh_resources(db_session, ["daily"], today=date(2026, 4, 2))
    assert refreshed == 1

    rows = list(
        db_session.scalars(
            select(DatasetLayerSnapshotCurrent).where(DatasetLayerSnapshotCurrent.dataset_key == "daily")
        )
    )
    by_stage = {row.stage: row for row in rows}
    assert by_stage["light"].status == "healthy"
    assert by_stage["light"].rows_out == 1
    assert by_stage["light"].lag_seconds == 0
